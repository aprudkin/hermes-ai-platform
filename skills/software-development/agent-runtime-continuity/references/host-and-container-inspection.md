# Host and container inspection

Use these probes only on the currently authorized runtime and SSH target. Inspect before changing anything; neither shell access nor a working key alone establishes administrative authority.

## Local boundary

Run `id`, `hostname`, `uname -srm` and `ps -p 1 -o comm=`. Inspect `/.dockerenv` and `/run/.containerenv` with existence checks, and inspect `/proc/self/mountinfo` for the root filesystem type using Python. Combine the results instead of treating a hostname or a single marker as decisive.

Do not require the SSH target's hostname to differ from the container's: shared or deliberately repeated hostnames are valid.

## Uploaded SSH key

1. Keep the private file out of command text, output, Git and instruction files. Restrict it with `chmod 600` or `os.chmod(path, 0o600)`.
2. Check the literal OpenSSH header and footer before attempting authentication. Request the original file when pasted delimiters are damaged; do not silently repair the supplied credential.
3. Run `ssh-keygen -y -P '' -f "$SSH_KEY"` with captured output and a timeout to verify an unencrypted key can be read. Compare its first two public-key fields with the supplied `.pub` file in code; output only the match result. A passphrase requirement is not proof the key is corrupt, and a passphrase must use a protected entry path.
4. Save the validated pair outside the upload cache before relying on it for future work. Use a private profile-local credential directory, reject symlink targets and unexpected ownership, keep directory ancestry 0700 and credential/config files 0600, and copy the original bytes without exposing them. Preserve the pinned known-hosts file and an explicit SSH configuration alongside the key. If an existing saved key differs, inspect rather than silently overwriting it. Put the reusable connection command in the relevant operational reference, not the key material in memory or Git; cached attachments can be evicted independently of container restarts.
5. Probe the explicitly supplied host/port with `socket.create_connection` if reachability is uncertain. Record timeout/refusal separately from a returned SSH banner; neither timeout nor refusal alone identifies a firewall rule.

## Authenticated read-only probe

Use the specified SSH login rather than trying a list of likely accounts. Once the host key has been accepted through the intended trust procedure, use a strict known-hosts check:

```bash
ssh -F /dev/null -i "$SSH_KEY" \
  -o IdentitiesOnly=yes -o BatchMode=yes \
  -o ConnectTimeout=8 -o ConnectionAttempts=1 \
  -o StrictHostKeyChecking=yes \
  -o UserKnownHostsFile="$KNOWN_HOSTS" \
  "$SSH_USER@$SSH_HOST" \
  'id; hostname; systemd-detect-virt; ps -p 1 -o comm=; sudo -n -l'
```

Capture exit status, stdout and stderr without printing the private key. When authentication fails, one `ssh -v` retry can distinguish a key that was not loaded from a key that was offered and rejected; select only the relevant diagnostics. Do not label a rejected offered key as a connectivity problem. After the owner repairs server authorization, re-test the same supplied key and login rather than rotating local credentials or trying other users.

## Persistent access for the manager installation

Use the profile-local SSH configuration at `/opt/data/profiles/manager/credentials/ssh/hermes-minimal/config` for the authorized host alias `hermes-minimal`: `ssh -F /opt/data/profiles/manager/credentials/ssh/hermes-minimal/config hermes-minimal '<command>'`. It selects `chebi@PRIVATE_SERVER_HOST`, the protected `id_ed25519`, and the pinned `known_hosts` in that same private directory. The account has verified noninteractive sudo; SSH login as root is not a substitute. Apply the persistence and permission checks above to this directory; the files belong to the manager UID. Suppress fingerprints as well as key contents from verbose authentication diagnostics.

The host data directory `/opt/hermes/data` is bind-mounted at `/opt/data`; persistent key files under the manager profile were byte-compared from both namespaces. This establishes disk persistence, not proof of a reboot test or survival of disk loss. A full backup created before a key was saved does not contain that key. Distinguish a valid key file, correct file permissions, an actually offered key and server acceptance; do not retrospectively attribute every publickey denial to one cause when several inputs changed.

## Persistence mapping

After authorization is established, inspect selected `docker inspect` fields: container identity/image, health and mount source/destination. Do not print the complete container configuration, which can contain secrets.

Find the host source of the active runtime-data mount. Compute SHA-256 of the active profile's persona both inside the container and at its mapped host path. If they match and the bind mount establishes the mapping, these are one persisted file viewed through two namespaces; do not overwrite one side as if it were an independent stale copy. Keep repository templates and cached prompts as separate layers.
