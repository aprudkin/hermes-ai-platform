---
name: docker-offline-host-preparation
description: "Use when preparing Docker for an offline migration test."
metadata:
  hermes:
    tags: [docker, migration, security, preparation]
---
# Scoped Docker preparation, not production migration

Load blast-radius, hermes-agent when applicable, and current official Docker Debian/firewall/containerd/dockerd documentation. Read actual task scope and repository guides; historical provisioning checklists do not grant authority.

## Preconditions

- Use explicit strict pinned SSH, no agent forwarding or multiplexing. Distinguish a TOFU pin from independent provider-console verification. Do not deliver private recovery state before the trust/storage/authority gate.
- Inspect active workloads through processes/executables, system/user units, timers/crontabs, listeners, runtimes/packages, data roots and sockets. A stale socket, empty runtime directory or loaded AppArmor profile does not establish an active runtime; an absent named app path does not prove an empty host. Preserve other administrators' private directories.
- Check dpkg audit, APT origins/sources, live package locks/jobs, free disk/inodes/RAM, SSH effective configuration, nft/iptables forwarding, routes, unattended and needrestart policy. Use subprocess argv for dpkg-query formats containing `${...}`; shell double quotes corrupt them.
- Save private prechange snapshots, ABSENT-path manifest, package versions, firewall/routes/sysctls and protected-file hashes/metadata. Write receipts with actual remote return codes and propagate failure to the controller.

## Minimal installation

- Use official HTTPS signing key and isolated Signed-By APT source, successful signed index refresh, exact stable candidate versions discovered live. Do not curl-pipe-shell, invent versions, replace occupied stores or grant docker-group access unnecessarily.
- Simulate the exact minimal no-recommends/no-remove transaction; stop on unapproved upgrades/removals/restarts. Review maintainer scripts before package-induced service starts. Scoped NEEDRESTART_MODE=l can avoid unrelated automatic needrestart actions but does not block maintainer scripts; never claim otherwise or disable security updates globally.
- If existing native nft forwarding denies all forwarding, do not weaken it for a network-none smoke. A fresh daemon may use `bridge: none` and `ip-forward: false` for an explicitly offline-only stage while leaving Docker iptables/ip6tables management enabled. This is not general production networking readiness. Record Docker's generated chains and verify host policy/routes/sysctls remain unchanged; an accept in another base chain does not override a drop.
- Validate the new config before initial daemon start, without forcing overlay2 or switching data-root. When using an extracted deb's dockerd for prevalidation, prepend that staging bin to only the validation process PATH so its docker-proxy is discoverable; a missing staged proxy is not a reason to disable proxy/security settings.
- Verify installed Engine/CLI/containerd/Buildx/Compose, actual image store, cgroups, socket group/mode, listeners and unchanged neighbors. Compose major may not be v2. On fresh Engine29+ expect containerd store but prove DriverStatus and both Docker/containerd storage paths. Leave third-party update maintenance explicit rather than assuming Debian unattended covers it.

## Harmless runtime proof

- Inventory image/tag mappings before pull. Use a trusted minimal public image, record actual RepoDigest/platform, inspect baked Env/Volumes, then create by digest with unique name and run labels.
- Override entrypoint, disable healthcheck, restart no, network none, no ports/host mounts/socket/devices, nonroot UID, read-only, cap-drop ALL, no-new-privileges, CPU/memory/PID/swap limits and bounded logs. Do not launch restored gateway/scheduler or contact production APIs.
- Prove flags via inspect and the live process: CapEff, NoNewPrivs, seccomp, AppArmor, namespaces, cgroup values, root mount ro and failed write on an ordinarily writable rootfs path. Check only loopback and empty routes, not real API probes. Readonly rootfs is not a complete security boundary.
- Keep exited inspect/logs/OOM/restart result, remove only exact owned container after checking its label, then read back absence. Do not prune or delete images/volumes globally. Retained public image is a documented artifact, not proof of vulnerability freshness.
- Synthetic tar/rsync numeric UID/GID/mode/POSIX ACL/user.xattr roundtrips can prove host tooling independently of archive availability. Do not equate these with security.* attribute acceptance or real restore. Keep a new private work directory away from another admin's rehearsal tree; restored destination must remain absent.

## Disposable reboot/fencing VM

For an authorized user-space QEMU/TCG guest on a shared target, read [isolated VM rehearsal](references/user-space-qemu.md). This permits guest-only execution, not host reboot or production admission.

## Closure

Compare host nft structure excluding volatile counters, routes, forwarding, protected hashes and service PIDs/start times. Verify fresh SSH, listeners, package health and resource availability after cleanup. Archive raw evidence privately with end-to-end digest verification; publish only sanitized results with exact issue GET readback and durable intent/HTTP receipt (no blind POST retry).

Report partial acceptance when host identity, encryption/retention, full archive, peak restore budget/host-side limits, exact-image compatibility, bridge/public-port networking, IPv6/reboot/alerts or actual agent acceptance remain untested. Do not let those gates block independent harmless preparation, and do not convert successful smoke into production readiness. Conditional rollback must re-inventory consumers and never blindly restore global firewall snapshots, delete stores or downgrade storage.

For explicitly authorized cancellation cleanup, separate owned work-tree deletion from package/config/store rollback and report after each requested step. Preserve prechange evidence until dependent rollback completes. Before deleting exact roots, recheck ownership/inodes, mount references, process FDs/maps/exe/cwd and unit/cron/startup references; reject unexpected owners or consumers. Measure synchronized statvfs free/available deltas against allocated du usage, then verify absence and protected services/configs over a fresh pinned SSH connection. Deliver scripts over stdin and retain receipts locally when remote cleanup artifacts are forbidden; do not create .disabled/.bak copies as an implicit rollback.

For explicit package cancellation, derive the exact package/version/status delta from the original dpkg inventory, inspect the matching purge simulation and maintainer scripts, then execute the approved transaction and verify the entire surviving map equals baseline. Check loaded-library/executable consumers as well as runtime stores; a reverse dependency may only be a recommendation, so prove the live service's actual backend (e.g. Fail2ban native nftables before removing newly added iptables). Remove only individually proven task-downloaded debs by package/version/hash/metadata; preserve unrelated cache files. Treat package purge, custom config, runtime sockets/directories and kernel firewall tables as separate residual classes. A preexisting stale socket with a group ID is not proof that this task created the group, and recreating an active socket is not a valid rollback.
