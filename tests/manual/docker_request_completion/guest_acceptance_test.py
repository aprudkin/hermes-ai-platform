#!/usr/bin/env python3
"""Explicit disposable/no-NIC guest ONLY; real Docker, no production admission."""
import hashlib,json,os,signal,subprocess,sys,time,unittest
from pathlib import Path
if os.environ.get('IVM_DISPOSABLE_REVIEW')!='no-network-generated-state-only':
 print('explicit disposable guest opt-in required',file=sys.stderr)
 raise SystemExit(2)
sys.path.insert(0,'/opt/ivm/repo')
from hermes_migration_controller import atomic_json,Refused
from hermes_migration_preparation import PreparationSite
from serial_authority import SerialAuthority
ROOT=Path('/var/lib/ivm-review')/str(time.time_ns())
def cmd(*a):return subprocess.check_output(a,text=True).strip()
def waitfor(fn,seconds=30):
 end=time.monotonic()+seconds
 while time.monotonic()<end:
  value=fn()
  if value:return value
  time.sleep(.1)
 raise AssertionError('bounded observation timed out')
class Acceptance(unittest.TestCase):
 def test_01_completed_request_allows_scoped_fence(self):
  a=self.fixture('complete'); a.operation('start',time.monotonic()+60)
  self.assertTrue(a.inspect()['State']['Running'])
  receipt=self.fence(a)
  self.assertTrue(receipt['remote_operations_revoked']);self.assertFalse(receipt['production_ready'])
  self.assertTrue(a.path.joinpath('data/processed.log').read_bytes())
 def test_02_revocation_denies_new_request(self):
  a=self.fixture('revoked');self.fence(a)
  with self.assertRaises(Refused):a.operation('start',time.monotonic()+60)
  self.assertFalse(a.inspect()['State']['Running'])
 def test_03_expired_request_denied_before_dispatch(self):
  a=self.fixture('expired')
  with self.assertRaises(Refused):a.operation('start',time.monotonic()-1)
  self.assertFalse(a.inspect()['State']['Running'])
 def test_04_sigkill_intent_is_not_completion(self):
  a=self.fixture('killed-intent');self.crash(a,'intent')
  self.assertFalse(a.inspect()['State']['Running'])
  receipt=self.fence(a)
  self.assertFalse(receipt['remote_operations_revoked'],'lost client/lock is not daemon completion')
  self.assertEqual(json.loads((a.path/'start.json').read_text())['phase'],'intent')
 def test_05_sigkill_after_effect_retains_delta_and_uncertainty(self):
  a=self.fixture('killed-effect');self.crash(a,'complete')
  self.assertTrue(a.inspect()['State']['Running'])
  before={p.name:p.read_bytes() for p in (a.path/'data').iterdir()}
  self.assertIn(b'processed-start',before['processed.log'])
  self.assertFalse(self.fence(a)['remote_operations_revoked'])
  with self.assertRaises(Refused):a.operation('start',time.monotonic()+60)
  self.assertEqual(before,{p.name:p.read_bytes() for p in (a.path/'data').iterdir()})
 def test_06_accepted_restart_survives_killed_client_and_deadline(self):
  a=self.fixture('accepted');a.operation('start',time.monotonic()+60)
  old=a.inspect()['State']['StartedAt'];events=a.path/'events.jsonl'
  with events.open('w') as f:
   observer=subprocess.Popen(['docker','events','--since',str(int(time.time())-1),'--filter','container='+a.cid,'--format','{{json .}}'],stdout=f)
  self.addCleanup(lambda:observer.poll() is None and observer.terminate())
  code="import sys,time;from pathlib import Path;sys.path[:0]=['/opt/ivm/repo','/opt/ivm'];from serial_authority import SerialAuthority;SerialAuthority(Path(sys.argv[1])).operation('restart',time.monotonic()+4)"
  child=subprocess.Popen([sys.executable,'-c',code,str(a.path)]);self.addCleanup(lambda:child.poll() is None and child.kill())
  def accepted():
   return any(json.loads(line).get('Action')=='kill' and json.loads(line).get('Actor',{}).get('Attributes',{}).get('signal')=='15' for line in events.read_text().splitlines())
  waitfor(accepted);child.kill();self.assertEqual(child.wait(timeout=10),-signal.SIGKILL)
  intent=(a.path/'restart.json').read_bytes()
  self.assertFalse(self.fence(a)['remote_operations_revoked'])
  waitfor(lambda:time.monotonic()>=json.loads(intent)['deadline'])
  self.assertEqual(a.inspect()['State']['StartedAt'],old,'must observe old instance after expiry before late restart')
  expiry_probe=time.monotonic()
  waitfor(lambda:a.inspect()['State']['Running'] and a.inspect()['State']['StartedAt']!=old,seconds=50)
  self.assertGreater(time.monotonic(),json.loads(intent)['deadline'])
  self.assertEqual((a.path/'restart.json').read_bytes(),intent)
  self.assertFalse(self.fence(a)['remote_operations_revoked'])
  atomic_json(a.path/'observed-late-effect.json',{'before_started_at':old,'after_started_at':a.inspect()['State']['StartedAt'],'client_sigkill':True,'accepted_by_daemon_signal15':True,'original_deadline':json.loads(intent)['deadline'],'old_instance_observed_after_deadline_at_monotonic':expiry_probe,'observed_monotonic':time.monotonic(),'admission':False})
  observer.terminate();observer.wait(timeout=10)
 def test_07_trusted_root_bypass_is_not_claimed_prevented(self):
  a=self.fixture('admin');self.assertTrue(self.fence(a)['fenced'])
  cmd('docker','start',a.cid)
  self.assertTrue(a.inspect()['State']['Running'])
  self.assertFalse(a.target_probe({})['fenced'])
 def test_08_wrong_boot_refuses_admission_and_fence_proof(self):
  a=self.fixture('wrong-boot');a.binding['boot']='not-this-boot'
  with self.assertRaises(Refused):a.operation('start',time.monotonic()+60)
  self.assertFalse(self.fence(a)['fenced'])
 def test_09_foreign_completion_cannot_clear_intent(self):
  a=self.fixture('foreign');a.operation('start',time.monotonic()+60)
  p=a.path/'start.json';r=json.loads(p.read_text());r['cid']='another-container';atomic_json(p,r)
  self.assertFalse(self.fence(a)['remote_operations_revoked'])
 def test_10_uncertain_start_blocks_other_enabling_action(self):
  a=self.fixture('unresolved');self.crash(a,'intent')
  with self.assertRaises(Refused):a.operation('restart',time.monotonic()+60)
  self.assertFalse(a.inspect()['State']['Running'])
 def test_11_fence_waits_for_terminal_rpc_before_stop(self):
  a=self.fixture('drain');a.operation('start',time.monotonic()+60)
  code="import sys,time;from pathlib import Path;sys.path[:0]=['/opt/ivm/repo','/opt/ivm'];from serial_authority import SerialAuthority;SerialAuthority(Path(sys.argv[1])).operation('restart',time.monotonic()+60)"
  child=subprocess.Popen([sys.executable,'-c',code,str(a.path)]);self.addCleanup(lambda:child.poll() is None and child.kill())
  waitfor(lambda:(a.path/'restart.json').exists())
  receipt=self.fence(a);self.assertEqual(child.wait(timeout=10),0)
  self.assertEqual(json.loads((a.path/'restart.json').read_text())['phase'],'complete')
  self.assertTrue(receipt['remote_operations_revoked']);self.assertFalse(receipt['running'])
  self.assertGreaterEqual((a.path/'data/processed.log').read_text().count('processed-start'),2)
 def crash(self,a,point):
  code="""import sys,time
from pathlib import Path
sys.path[:0]=['/opt/ivm/repo','/opt/ivm']
import serial_authority as m
p=Path(sys.argv[1]);point=sys.argv[2];original=m.atomic_json
def write(path,obj):
 if path.name=='start.json' and obj['phase']==point:
  if point=='intent':original(path,obj)
  (p/'crash-ready').write_text(point)
  time.sleep(90)
 else:original(path,obj)
m.atomic_json=write
m.SerialAuthority(p).operation('start',time.monotonic()+60)
"""
  child=subprocess.Popen([sys.executable,'-c',code,str(a.path),point]);self.addCleanup(lambda:child.poll() is None and child.kill())
  waitfor(lambda:(a.path/'crash-ready').exists());child.kill();self.assertEqual(child.wait(timeout=10),-signal.SIGKILL)
 def fixture(self,name):
  name=name+'-'+ROOT.name[-8:]
  p=ROOT/name;p.mkdir(parents=True,mode=0o700)
  data=p/'data';data.mkdir(mode=0o777);os.chmod(data,0o777)
  for n,v in [('processed.log','processed history\n'),('cancelled.json','{"cancelled":true}'),('uncertain.json','{"replay":false}')]:
   (data/n).write_text(v);os.chmod(data/n,0o666)
  cid=cmd('docker','create','--name','ivm-review-'+name,'--label','ivm.review=true','--restart=no','--network=none','--read-only','--user=65534:65534','--cap-drop=ALL','--security-opt=no-new-privileges','--memory=32m','--cpus=.25','--pids-limit=32','--mount',f'type=bind,src={data},dst=/data','ivm-generated:fixture','/bin/sh','-c',"trap '' TERM; echo processed-start >> /data/processed.log; while :; do /bin/sleep 1; done")
  atomic_json(p/'binding.json',{'cid':cid,'boot':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'requester':'sole serialized guest test operator','run_id':name})
  a=SerialAuthority(p);self.addCleanup(self.cleanup,a);return a
 def cleanup(self,a):
  # Safety-only cleanup never fabricates completion for an uncertain RPC.
  subprocess.run(['docker','stop','-t','1',a.cid],check=True,capture_output=True)
 def fence(self,a):
  return PreparationSite(None,None,None,a).call('target_fence',dict(run_id=a.run,operation_id=a.run+':target_fence',action='target_fence'))
if __name__=='__main__':unittest.main(verbosity=2)
