"""Read-only MCP discovery through owner's loopback SSH tunnel."""
import asyncio,json,os,pathlib
BASE=pathlib.Path(os.environ.get('HERMES_HOME',pathlib.Path.home()/'.hermes'))/'browser'/'mac'
async def main():
 from mcp import ClientSession
 from mcp.client.streamable_http import streamable_http_client,create_mcp_http_client
 os.umask(0o077)
 BASE.mkdir(parents=True,exist_ok=True,mode=0o700)
 async with create_mcp_http_client(headers={'Host':'localhost:8931'}) as http:
  async with streamable_http_client('http://127.0.0.1:18931/mcp',http_client=http) as streams:
   async with ClientSession(streams[0],streams[1],read_timeout_seconds=60) as session:
    init=await session.initialize(); tools=await session.list_tools()
    print(json.dumps({'server':init.server_info.model_dump(),'tools':[t.name for t in tools.tools]}))
    matches=[t for t in tools.tools if t.name=='browser_tabs']
    if matches:
     print(json.dumps({'browser_tabs_schema':matches[0].input_schema}))
     result=await session.call_tool('browser_tabs',{'action':'list'},read_timeout_seconds=50)
     data=result.model_dump(by_alias=True)
     (BASE/'probe-result.private.json').write_text(json.dumps(data,ensure_ascii=False,indent=2))
     print(json.dumps(data,ensure_ascii=False))
if __name__=='__main__':
 asyncio.run(main())
