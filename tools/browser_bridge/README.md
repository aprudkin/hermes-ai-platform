# Explicit browser bridges

These are versioned copies of the installed Mac MCP file queue and isolated
Chromium runner, with inert imports and configurable profile/executable paths.
They are **not installed, started or connected by this repository**.

- `mac_browser_client.py` owns one locked MCP session through an existing
  loopback SSH tunnel (`127.0.0.1:18931`, MCP Host `localhost:8931`). It consumes
  explicit request files and retains started/uncertain requests instead of
  automatically replaying them. It refuses the unsafe code tool.
- `mac_browser_call.py` queues one JSON request from stdin and awaits its result.
- `mac_browser_probe.py` is an explicit operator-run discovery/tab-list probe,
  not a scheduled monitor. Its results are private state.
- `chebi_browser.py` launches a separate persistent browser profile, binds CDP to
  loopback, checks profile ownership, and invokes the existing Hermes config CLI
  only when explicitly run. It is not permission to inspect a human's browser.

Set `HERMES_HOME` to the intended private profile. Queues, browser profiles,
locks, logs and tool discovery stay under its `browser/` directory, never Git.
Set `AGENT_BROWSER_EXECUTABLE_PATH` to a separately reviewed Chromium executable;
`HERMES_COMMAND` may name an explicit Hermes launcher. The Mac helpers require
an installed compatible `mcp` Python package and an owner-established tunnel.
No tunnel, browser, session/cookies, keys or account access is supplied here.

Use Hermes' vault tools for website credentials. A browser connection is not
permission to enter credentials through arbitrary scripts. Do not change
loopback bindings or expand host/chat access to make a probe pass.

`bash tests/runtime_helpers_test.sh` proves import isolation without network or
process starts. It does **not** prove a current Mac connection, authenticated
website session, browser launch or tunnel health; none was exercised by this
source reconciliation.
