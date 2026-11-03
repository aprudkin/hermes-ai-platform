# Browser session continuity

Use when preserving an agent-owned signed-in browser or connecting a human's interactive browser to a remote agent. This procedure does not establish that any Google login or remote extension bridge has already succeeded.

## 1. Identify the intended access and connection boundary

1. Determine whether the goal is incoming mail, a mail API, or interactive website access through an identity provider. Forwarding mail does not grant a browser session or the right to send as the source mailbox.
2. Locate the agent, browser and connector processes independently. An extension installed on a personal computer normally talks to a local companion; it does not automatically expose that browser to a server-hosted agent.
3. If an existing extension is mentioned, inspect its exact name, publisher and connection status first. Ask for a screenshot without tokens when the local installation is not observable; do not substitute an assumed extension or a generic install command.
4. For recommendations, verify the extension's store listing and its publisher's setup documentation. Distinguish similarly named projects by publisher/domain. Report subscription cost, required companion process and whether the remote-agent transport is documented or still untested. Prefer a concrete supported candidate over a catalogue of vaguely similar browser tools.
5. Give the user one appropriate next action. Do not imply that installing an extension completes remote connectivity. Establish the operating system only when needed for the actual local command. Keep browser-control endpoints off the public internet.

### Verify a remote extension connection in layers

1. Treat a user's `Listening on http://localhost:<port>` output as evidence only of the companion on that user's computer. Use the exact advertised MCP path; a server-side localhost probe addresses the agent server, not the user's Mac. An absent server listener before transport is configured does not diagnose a broken extension.
2. Establish the authorized private transport separately. For SSH forwarding, inspect effective `sshd -T -C` settings for the relevant user/address and applicable key restrictions before selecting a route; forwarding permission and SSH authentication are different prerequisites. A previous failed forwarding attempt is not proof of a permanent global prohibition. Do not weaken SSH policy simply to make a diagnostic pass.
3. For an approved reverse tunnel, specify both loopback binds explicitly and use `ExitOnForwardFailure=yes` plus keepalives. Keep the companion and tunnel windows open for the manual test. Explain that a silent long-running SSH command is expected, but is not an end-to-end success receipt. Resolve first-use host identity and missing public-key authorization before asking the user to retry blindly.
4. From the agent side, verify the forwarded endpoint, then perform real MCP initialization and tool discovery, then a harmless browser action after extension approval. Check that the selected browser profile is the intended agent account. Report these as separate milestones; a listening port or tool list is not signed-in Google access.
5. Only after a successful connection test configure persistent client integration or automatic startup. Keep an uncompleted remote bridge explicitly unverified rather than saving its proposed command sequence as a known-working deployment.

## 2. Establish a persistent, correctly scoped browser

1. Read current runtime documentation, then verify that the installed code actually consumes the proposed configuration keys. A CLI can save an unknown key without implementing it. Check the launched process's real profile path instead of treating a successful config write as adoption.
2. Use a separate private profile for the agent account. Do not copy unrelated human cookies or select another saved account simply because its login origin matches.
3. Give the profile exactly one owning browser process. Hold a stable lock in a dedicated runner when managing it yourself. After a close request, confirm the owning process exited before relaunching; a second browser can otherwise contend for cookie and database files.
4. Bind a managed CDP endpoint to loopback, validate its live browser endpoint, and retain only private connection metadata. If a driver daemon outlives a changed endpoint, use a fresh named driver session rather than assuming it retargeted itself.
5. Verify the connection with a harmless uniquely marked tab and read that tab back from the intended CDP endpoint. Do not equate a browser target ID with the websocket endpoint UUID; they are not a dependable identity assertion.

## 3. Prove persistence before accepting credentials

1. Through the exact agent tool path, create a nonsecret test cookie with an explicit future expiry on a harmless test origin.
2. Gracefully close that browser and observe its process exit. Relaunch the same profile, refresh the endpoint and reconnect through a fresh driver session where needed.
3. Read back only the named test cookie, assert its value, then delete it. This demonstrates profile persistence without printing real cookies or asking the user to repeat an actual login as a diagnostic.
4. Test the target service separately. A rendered sign-in page is not authenticated access, and cookie persistence is not evidence that the identity provider accepts that browser. Report an observed refusal accurately; do not turn an unresolved login attempt into a recommended bypass recipe.
5. Use the authorized secret-entry mechanism for credentials and human participation for required challenges. Never include bearer URLs, cookies, tokens or password fields in screenshots/logs intended for chat or Git.
6. Distinguish persistence across a browser restart from restart supervision, host-boot startup and cross-host authentication validity. Only claim each lifecycle property after its own test.

## 4. Include the browser in recovery

1. Add newly launched browsers, their runners and profile databases to the live writer inventory before freezing state. A browser introduced during migration preparation invalidates an earlier complete-writer claim.
2. Gracefully stop and checkpoint the owned browser before taking a cold snapshot; preserve the private profile under the same custody policy as other credentials.
3. Re-resolve machine-local executable paths and ephemeral CDP endpoints after restoration. Preserve the profile, but do not blindly activate a restored endpoint pointing to the old process or host.
4. Revalidate service access on the recovered browser: matching profile bytes do not guarantee portable OS-keychain encryption, valid sessions or provider acceptance.
