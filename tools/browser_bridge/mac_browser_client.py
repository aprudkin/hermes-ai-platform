"""Persistent, local file-queue MCP session over owner's SSH tunnel.
No autonomous browsing: executes only explicit local request files.
"""
import asyncio,json,os,pathlib,fcntl,datetime,sys
BASE=pathlib.Path(os.environ.get('HERMES_HOME',pathlib.Path.home()/'.hermes'))/'browser'/'mac'
def atomic(path,data):
 tmp=path.with_suffix('.tmp'); tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2)); tmp.replace(path)
async def main():
 from mcp import ClientSession
 from mcp.types import Implementation
 from mcp.client.streamable_http import streamable_http_client,create_mcp_http_client
 os.umask(0o077)
 BASE.mkdir(parents=True,exist_ok=True,mode=0o700)
 for d in ['requests','results']:(BASE/d).mkdir(mode=0o700,exist_ok=True)
 lock=(BASE/'client.lock').open('a'); fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 async with create_mcp_http_client(headers={'Host':'localhost:8931'}) as http:
  async with streamable_http_client('http://127.0.0.1:18931/mcp',http_client=http) as streams:
   async with ClientSession(streams[0],streams[1],read_timeout_seconds=90,client_info=Implementation(name='Chebi',version='1.0')) as session:
    init=await session.initialize(); tools=await session.list_tools()
    atomic(BASE/'tools.private.json',{'tools':[t.model_dump(by_alias=True) for t in tools.tools]})
    atomic(BASE/'client-status.json',{'state':'connected','server':init.server_info.model_dump(),'pid':os.getpid()})
    print('MAC_MCP_SESSION_READY',flush=True)
    while True:
     for path in sorted((BASE/'requests').glob('*.json')):
      result_path=BASE/'results'/path.name
      if result_path.exists():continue
      request=json.loads(path.read_text())
      intent=path.with_suffix('.started')
      if intent.exists():
       atomic(result_path,{'error':'uncertain previous request; not automatically retried'});continue
      intent.write_text('started')
      try:
       name=request['tool']; args=request.get('arguments',{})
       # No credential entry / arbitrary local code tool via this bridge.
       assert name in {t.name for t in tools.tools} and name!='browser_run_code_unsafe'
       result=await session.call_tool(name,args,read_timeout_seconds=80)
       atomic(result_path,result.model_dump(by_alias=True))
      except Exception as e:
       atomic(result_path,{'error':type(e).__name__})
     await asyncio.sleep(.3)
if __name__=='__main__':
 try: asyncio.run(main())
 finally:
  if BASE.is_dir(): atomic(BASE/'client-status.json',{'state':'disconnected'})
