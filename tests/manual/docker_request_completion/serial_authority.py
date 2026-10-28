"""Narrow disposable guest authority: serialized requester + terminal receipts.
Not migration-site-v2 admission. No effect-time lease or generic Docker barrier.
"""
import contextlib,fcntl,http.client,json,socket,subprocess,time
from pathlib import Path
from hermes_migration_controller import atomic_json,Refused
class UnixHTTP(http.client.HTTPConnection):
 def connect(self):
  self.sock=socket.socket(socket.AF_UNIX);self.sock.settimeout(45);self.sock.connect('/var/run/docker.sock')
class SerialAuthority:
 def __init__(self,path):
  self.path=Path(path);self.binding=json.loads((self.path/'binding.json').read_text());self.cid=self.binding['cid'];self.run=self.binding['run_id']
 @contextlib.contextmanager
 def hold(self,request=None):
  if request is not None and (request['run_id']!=self.run or request['operation_id']!=self.run+':'+request['action']):raise Refused('identity mismatch')
  with (self.path/'lock').open('a') as f:
   fcntl.flock(f,fcntl.LOCK_EX)
   yield
 def inspect(self):return json.loads(subprocess.check_output(['docker','inspect',self.cid],text=True))[0]
 def preflight(self,r):return {'run_id':self.run,'ready':False,'production_ready':False,'scope':'disposable serialized requester only'}
 def same_boot(self):return self.binding['boot']==Path('/proc/sys/kernel/random/boot_id').read_text().strip()
 def operation(self,action,deadline,point=None):
  if action not in ('start','restart'):raise Refused('unsupported action')
  with self.hold():
   if not self.same_boot():raise Refused('boot changed; reconcile rather than renew')
   if time.monotonic()>=deadline:raise Refused('original deadline expired')
   if self.pending():raise Refused('unresolved prior operation; no enabling commands')
   if (self.path/'revoked.json').exists():raise Refused('requester revoked')
   op=self.path/(action+'.json')
   if op.exists():raise Refused('operation never replayed')
   atomic_json(op,{'action':action,'cid':self.cid,'boot':self.binding['boot'],'deadline':deadline,'phase':'intent'})
   h=UnixHTTP('localhost');h.request('POST',f'/v1.45/containers/{self.cid}/{action}?t=8',headers={'Content-Length':'0'})
   response=h.getresponse();response.read();h.close()
   if response.status!=204:raise Refused('non-success RPC is uncertain')
   atomic_json(op,{'action':action,'cid':self.cid,'boot':self.binding['boot'],'deadline':deadline,'phase':'complete','http_status':response.status})
 def pending(self):
  pending=[]
  for action in ('start','restart'):
   p=self.path/(action+'.json')
   if p.exists():
    r=json.loads(p.read_text())
    if not (r.get('phase')=='complete' and r.get('cid')==self.cid and r.get('boot')==self.binding['boot'] and r.get('action')==action and r.get('http_status')==204):pending.append(p.name)
  return pending
 def target_fence(self,r):
  atomic_json(self.path/'revoked.json',{'run_id':self.run,'boot':self.binding['boot']})
  if self.pending():return self.target_probe(r)
  subprocess.run(['docker','update','--restart=no',self.cid],check=True,capture_output=True)
  subprocess.run(['docker','stop','-t','1',self.cid],check=True,capture_output=True)
  return self.target_probe(r)
 def target_probe(self,r):
  i=self.inspect();fenced=self.same_boot() and not self.pending() and (self.path/'revoked.json').exists() and not i['State']['Running'] and i['HostConfig']['RestartPolicy']['Name']=='no'
  return {'run_id':self.run,'running':i['State']['Running'],'fenced':fenced,'remote_operations_revoked':fenced,'production_ready':False,'scope':'disposable sole serialized requester; no daemon-wide claim'}
