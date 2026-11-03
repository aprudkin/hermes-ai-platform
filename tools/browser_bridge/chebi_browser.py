"""Run Chebi's isolated persistent Chromium; bind CDP to loopback only."""
import fcntl,os,pathlib,subprocess,time,json,urllib.request,signal

def main():
    os.umask(0o077)
    root=pathlib.Path(os.environ.get('HERMES_HOME',pathlib.Path.home()/'.hermes'))/'browser'; root.mkdir(mode=0o700,exist_ok=True)
    profile=root/'chebi-profile'; profile.mkdir(mode=0o700,exist_ok=True)
    lock=(root/'chebi-profile.lock').open('a'); fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    portfile=profile/'DevToolsActivePort'
    # Refuse to open an already active profile from outside this runner.
    if portfile.exists():
     try:
      old=portfile.read_text().splitlines()
      with urllib.request.urlopen('http://127.0.0.1:'+str(int(old[0]))+'/json/version',timeout=2) as r:
       if json.load(r)['webSocketDebuggerUrl'].endswith(old[1]): raise RuntimeError('profile already running')
     except (OSError,ValueError,KeyError,IndexError): pass
     portfile.unlink()
    exe=os.environ.get('AGENT_BROWSER_EXECUTABLE_PATH')
    if not exe: raise RuntimeError('Set AGENT_BROWSER_EXECUTABLE_PATH to the reviewed Chromium executable')
    with (root/'chromium.private.log').open('a') as log:
     p=subprocess.Popen([exe,'--no-sandbox','--disable-dev-shm-usage','--remote-debugging-address=127.0.0.1','--remote-debugging-port=0','--user-data-dir='+str(profile),'about:blank'],stdout=log,stderr=log)
     def stop(sig,frame):
      if p.poll() is None: p.terminate()
     signal.signal(signal.SIGTERM,stop); signal.signal(signal.SIGINT,stop)
     try:
      deadline=time.monotonic()+20
      while not portfile.exists():
       if p.poll() is not None or time.monotonic()>deadline: raise RuntimeError('browser launch failed')
       time.sleep(.1)
      parts=portfile.read_text().splitlines(); url='http://127.0.0.1:'+str(int(parts[0]))
      with urllib.request.urlopen(url+'/json/version',timeout=5) as r:
       assert json.load(r)['webSocketDebuggerUrl'].endswith(parts[1])
      subprocess.run([os.environ.get('HERMES_COMMAND','hermes'),'config','set','browser.cdp_url',url],check=True,stdout=subprocess.DEVNULL)
      print('CHEBI_BROWSER_READY',flush=True)
      p.wait()
     finally:
      if p.poll() is None:
       p.terminate()
       try: p.wait(timeout=10)
       except subprocess.TimeoutExpired: p.kill(); p.wait()

if __name__=='__main__':
    main()
