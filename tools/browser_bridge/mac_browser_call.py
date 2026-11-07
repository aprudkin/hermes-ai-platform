"""Submit one explicit request to Chebi's persistent Mac MCP client."""
import json,os,pathlib,sys,time,uuid

def main():
    os.umask(0o077)
    b=pathlib.Path(os.environ.get('HERMES_HOME',pathlib.Path.home()/'.hermes'))/'browser'/'mac'
    payload=json.loads(sys.stdin.read()); ident=uuid.uuid4().hex
    p=b/'requests'/(ident+'.json'); tmp=p.with_suffix('.tmp'); tmp.write_text(json.dumps(payload)); tmp.replace(p)
    r=b/'results'/p.name; deadline=time.monotonic()+85
    while not r.exists() and time.monotonic()<deadline: time.sleep(.2)
    if not r.exists(): print(json.dumps({'pending_request':ident})); sys.exit(2)
    data=json.loads(r.read_text())
    for c in data.get('content',[]):
     if c.get('type')=='text': print(c['text'])
    if data.get('error'): print(json.dumps({'error':data['error']}))
    sys.exit(1 if data.get('isError') or data.get('error') else 0)

if __name__=='__main__':
    main()
