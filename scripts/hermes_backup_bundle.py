#!/usr/bin/env python3
"""Capture and structurally verify private Hermes personal or recovery bundles.

No Docker or host mutations occur in verify/program. Capture pauses only its
identified container, stores secrets privately, and unpauses before packaging.
Structural verification is not proof that a restore or inference will succeed.
"""
import datetime
import fcntl
import gzip
import hashlib
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path, PurePosixPath

FORMAT = "hermes-recovery-bundle"
PERSONAL_FORMAT = "hermes-personal-bundle"
PAYLOADS = {"state.tar", "image.tar", "compose.restore.json", "RESTORE.md",
            "container-inspect.json", "image-inspect.json", "verify.py"}
PERSONAL_PAYLOADS = PAYLOADS - {"image.tar"}
# Named components anywhere in app/data; uv's exact relative subpath anywhere;
# lazy-packages only at actual Hermes home roots. No general bin/cache/env,
# .local, database, large-file, or custom-application exclusions.
PERSONAL_POLICY = {
    "version": 1,
    "excluded_components": [".cache", ".npm", "node_modules", "__pycache__", ".venv", ".cli-venv"],
    "excluded_subpaths": [".local/share/uv"],
    "excluded_hermes_paths": ["data/lazy-packages", "data/profiles/<name>/lazy-packages"],
}
HEX = re.compile(r"sha256:[0-9a-f]{64}\Z")
SMALL_LIMIT = 16 * 1024 * 1024


class BundleError(Exception):
    pass


def require(condition, message):
    if not condition:
        raise BundleError(message)


def run(args, timeout=60, reject_diagnostics=False):
    # Neither Docker inspect output nor command stderr may reach the terminal.
    try:
        result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                check=True, timeout=timeout)
        # GNU tar can warn about failed ACL/xattr writes and still exit zero.
        # Restore is fail-closed even for such warnings, without leaking paths.
        require(not reject_diagnostics or not (result.stdout or result.stderr),
                "restore diagnostics reported; destination is incomplete (details withheld)")
        return result.stdout
    except (subprocess.SubprocessError, OSError):
        raise BundleError("external command failed or timed out") from None


def inspect(kind, target):
    args = ["docker", "image", "inspect", target] if kind == "image" else ["docker", "inspect", target]
    value = json.loads(run(args))
    require(isinstance(value, list) and len(value) == 1 and isinstance(value[0], dict),
            "invalid Docker inspection")
    return value[0]


def profile_for(container):
    cmd = container["Config"].get("Cmd")
    require(isinstance(cmd, list) and len(cmd) == 5 and cmd[:2] == ["hermes", "-p"]
            and cmd[3:] == ["gateway", "run"] and isinstance(cmd[2], str)
            and re.fullmatch(r"[A-Za-z0-9_-]+", cmd[2]), "unsupported gateway command")
    return cmd[2]


def validate_runtime(container, root):
    """Supported Docker metadata, independent of live state and local paths."""
    require(HEX.fullmatch(container.get("Image", "")), "invalid image identity")
    mounts = container.get("Mounts", [])
    require(len(mounts) == 1, "unsupported mounts")
    mount = mounts[0]
    require(mount.get("Type") == "bind" and mount.get("Source") == str(root / "data")
            and mount.get("Destination") == "/opt/data" and mount.get("RW") is True
            and mount.get("Propagation", "rprivate") == "rprivate", "unsupported data mount")
    host = container["HostConfig"]
    require(host.get("NetworkMode") == "host", "unsupported network mode")
    # These cannot be represented by this project's standalone restore contract.
    unsupported = ("Privileged", "ReadonlyRootfs", "Devices", "DeviceRequests", "DeviceCgroupRules",
                   "CapAdd", "CapDrop", "SecurityOpt", "ExtraHosts", "Dns", "DnsOptions", "DnsSearch",
                   "Links", "VolumesFrom", "Tmpfs", "PortBindings", "PublishAllPorts", "Sysctls",
                   "GroupAdd", "StorageOpt", "CgroupParent", "ContainerIDFile", "AutoRemove",
                   "VolumeDriver", "BlkioWeight", "BlkioWeightDevice", "BlkioDeviceReadBps",
                   "BlkioDeviceWriteBps", "BlkioDeviceReadIOps", "BlkioDeviceWriteIOps",
                   "CpuRealtimePeriod", "CpuRealtimeRuntime", "KernelMemory", "KernelMemoryTCP",
                   "Ulimits", "Annotations", "UseApiSocket", "CpuCount", "CpuPercent", "IOMaximumIOps", "IOMaximumBandwidth")
    require(not any(host.get(key) for key in unsupported), "unsupported container runtime options")
    for key, supported in (("PidMode", (None, "")), ("UTSMode", (None, "")),
                           ("UsernsMode", (None, "")), ("IpcMode", (None, "", "private")),
                           ("CgroupnsMode", (None, "", "private")),
                           ("Runtime", (None, "", "runc")),
                           ("Isolation", (None, "", "default"))):
        require(host.get(key) in supported, "unsupported namespace or runtime")
    config = container["Config"]
    require(not config.get("Tty") and not config.get("OpenStdin"), "interactive container unsupported")
    require(config.get("StopTimeout") is None, "custom stop timeout unsupported")
    require(not config.get("Domainname"), "custom domain unsupported")
    masked = ["/proc/asound", "/proc/acpi", "/proc/interrupts", "/proc/kcore", "/proc/keys",
              "/proc/latency_stats", "/proc/timer_list", "/proc/timer_stats", "/proc/sched_debug",
              "/proc/scsi", "/sys/firmware", "/sys/devices/virtual/powercap"]
    readonly = ["/proc/bus", "/proc/fs", "/proc/irq", "/proc/sys", "/proc/sysrq-trigger"]
    require(host.get("MaskedPaths") is None or sorted(host["MaskedPaths"]) == sorted(masked),
            "custom masked paths unsupported")
    require(host.get("ReadonlyPaths") is None or sorted(host["ReadonlyPaths"]) == sorted(readonly),
            "custom readonly paths unsupported")
    require(not host.get("ConsoleSize") or host["ConsoleSize"] == [0, 0], "custom console unsupported")
    return profile_for(container)


def validate_container(container, root, name):
    require(container.get("Name") == "/" + name and container.get("State", {}).get("Running")
            and not container["State"].get("Paused"), "container must be running and initially unpaused")
    profile = validate_runtime(container, root)
    for directory in (root, root / "app", root / "data"):
        require(directory.is_dir() and not directory.is_symlink(), "runtime directories must be real directories")
    for relative in ("app/docker-compose.yml", "app/gateway.env", "data/config.yaml"):
        path = root / relative
        require(path.is_file() and not path.is_symlink(), "required runtime file missing")
    if profile != "default":
        require((root / "data/profiles" / profile).is_dir()
                and not (root / "data/profiles" / profile).is_symlink(), "active profile missing")
    return profile


def layer_diff(container_id):
    lines = run(["docker", "diff", container_id]).decode("utf-8").splitlines()
    for line in lines:
        require(len(line) > 2 and line[:2] in ("A ", "C ", "D "), "invalid layer diff")
        path = line[2:]
        require(path.startswith("/"), "invalid layer diff")
        if path == "/opt/data" or path.startswith("/opt/data/"):
            continue
        # Only runtime scratch/supervisor state is intentionally excluded.
        # The immutable image export cannot preserve changes anywhere else.
        transient = any(path == prefix or path.startswith(prefix + "/")
                        for prefix in ("/run", "/tmp", "/var/tmp"))
        parent_metadata = line == "C /var"
        require(transient or parent_metadata,
                "image-layer customization is outside recovery coverage")
    return lines


def escape_compose(value):
    # Compose interpolates string values even when its input is JSON.
    if isinstance(value, str):
        return value.replace("$", "$$")
    if isinstance(value, list):
        return [escape_compose(item) for item in value]
    if isinstance(value, dict):
        return {key: escape_compose(item) for key, item in value.items()}
    return value


def restore_compose(container, root, tag, personal=False):
    validate_runtime(container, root)
    config, host = container["Config"], container["HostConfig"]
    restart = host.get("RestartPolicy", {})
    policy = restart.get("Name") or "no"
    require(policy in ("no", "always", "unless-stopped", "on-failure"), "unsupported restart policy")
    if policy == "on-failure" and restart.get("MaximumRetryCount"):
        policy += ":" + str(restart["MaximumRetryCount"])
    service = {"image": tag, "pull_policy": "missing" if personal else "never", "container_name": "hermes",
               "network_mode": host["NetworkMode"], "restart": policy,
               "volumes": [{"type": "bind", "source": str(root / "data"),
                            "target": "/opt/data", "read_only": False}],
               "environment": config.get("Env") or [],
               "command": config.get("Cmd"), "entrypoint": config.get("Entrypoint") or [],
               "user": config.get("User") or "", "working_dir": config.get("WorkingDir") or "",
               "logging": {"driver": host.get("LogConfig", {}).get("Type") or "json-file",
                           "options": host.get("LogConfig", {}).get("Config") or {}}}
    hostname = config.get("Hostname")
    if hostname and hostname != container["Id"][:12]:
        service["hostname"] = hostname
    if host.get("Init") is not None:
        service["init"] = host["Init"]
    if config.get("StopSignal"):
        service["stop_signal"] = config["StopSignal"]
    health = config.get("Healthcheck")
    if health:
        translated = {"test": health["Test"]}
        for field in ("Interval", "Timeout", "StartPeriod", "StartInterval"):
            if health.get(field):
                key = {"Interval": "interval", "Timeout": "timeout", "StartPeriod": "start_period",
                       "StartInterval": "start_interval"}[field]
                translated[key] = str(health[field]) + "ns"
        if health.get("Retries"):
            translated["retries"] = health["Retries"]
        service["healthcheck"] = translated
    resources = {"Memory": "mem_limit", "MemoryReservation": "mem_reservation", "MemorySwap": "memswap_limit",
                 "CpuShares": "cpu_shares", "CpuPeriod": "cpu_period", "CpuQuota": "cpu_quota",
                 "CpusetCpus": "cpuset", "PidsLimit": "pids_limit", "ShmSize": "shm_size",
                 "OomScoreAdj": "oom_score_adj"}
    for field, key in resources.items():
        if host.get(field):
            service[key] = host[field]
    require(not host.get("CpusetMems"), "NUMA memory affinity unsupported")
    if host.get("NanoCpus"):
        service["cpus"] = host["NanoCpus"] / 1_000_000_000
    if host.get("OomKillDisable") is not None:
        service["oom_kill_disable"] = host["OomKillDisable"]
    if host.get("MemorySwappiness") is not None:
        service["mem_swappiness"] = host["MemorySwappiness"]
    return escape_compose({"name": "hermes-recovery", "services": {"hermes": service}})


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def digest_file(path):
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            size += len(block)
            digest.update(block)
    return {"sha256": digest.hexdigest(), "size": size}


def personal_excluded(name):
    parts = PurePosixPath(name).parts
    if any(part in PERSONAL_POLICY["excluded_components"] for part in parts):
        return True
    if any(parts[index:index + 3] == (".local", "share", "uv") for index in range(len(parts) - 2)):
        return True
    return (parts[:2] == ("data", "lazy-packages")
            or (len(parts) >= 4 and parts[:2] == ("data", "profiles") and parts[3] == "lazy-packages"))


def personal_paths(root, deadline=None):
    """Yield retained paths without following symlinks or entering exclusions."""
    def walk_failed(error):
        raise BundleError("cannot scan personal state")
    for tree in (root / "data", root / "app"):
        for directory, dirs, files in os.walk(tree, followlinks=False, onerror=walk_failed):
            require(deadline is None or time.monotonic() < deadline, "personal snapshot scan timed out")
            dirs[:] = sorted(name for name in dirs
                             if not personal_excluded((Path(directory) / name).relative_to(root).as_posix()))
            yield Path(directory).relative_to(root).as_posix()
            directory_names = set(dirs)
            for name in dirs + sorted(files):
                path = Path(directory) / name
                relative = path.relative_to(root).as_posix()
                if not personal_excluded(relative) and (name not in directory_names or path.is_symlink()):
                    require(deadline is None or time.monotonic() < deadline, "personal snapshot scan timed out")
                    yield relative


def personal_snapshot(root, stage):
    # Enumerate during the owned pause. Feed only retained paths, without tar
    # recursion, so excluded first hardlink sources cannot capture the inode.
    deadline = time.monotonic() + 300
    paths = stage / "state-files.list"
    with paths.open("wb") as stream:
        for name in personal_paths(root, deadline):
            stream.write(os.fsencode(name) + b"\0")
    remaining = deadline - time.monotonic()
    require(remaining > 0, "personal snapshot scan timed out")
    run(["tar", "--numeric-owner", "--acls", "--xattrs", "-cf", str(stage / "state.tar"),
         "-C", str(root), "--no-recursion", "--null", "-T", str(paths)], timeout=remaining)


def require_space(root, image, personal=False):
    """Conservative staging budget, not a reservation or a whole-host audit."""
    if personal:
        size, entries = 0, 0
        for name in personal_paths(root):
            info = (root / name).lstat()
            entries += 1
            if stat.S_ISREG(info.st_mode):
                size += info.st_size
        budget = size + entries * 4096 + 64 * 1024 * 1024
        require(shutil.disk_usage(root).free >= budget, "insufficient staging space")
        return budget
    require(type(image.get("Size")) is int and image["Size"] >= 0, "invalid image size")
    size, entries = image["Size"], 0
    def walk_failed(error):
        raise BundleError("cannot estimate runtime staging space")
    for tree in (root / "app", root / "data"):
        for directory, dirs, files in os.walk(tree, followlinks=False, onerror=walk_failed):
            entries += len(dirs) + len(files) + 1
            for name in files:
                info = (Path(directory) / name).lstat()
                if stat.S_ISREG(info.st_mode):
                    size += info.st_size
    # Only one raw state snapshot and one image export live on the source.
    # Compression streams to the controller, which owns final verification.
    # Per-entry headers/xattrs and 64 MiB allow modest metadata/state growth.
    budget = size + entries * 4096 + 64 * 1024 * 1024
    require(shutil.disk_usage(root).free >= budget, "insufficient staging space")
    return budget


def interrupted(signum, frame):
    raise BundleError("capture interrupted or timed out")


def stage_reporter(location):
    """Only fixed stage labels/timings, never runtime paths or command output."""
    started = previous = time.monotonic()

    def report(label):
        nonlocal previous
        now = time.monotonic()
        def duration(value):
            seconds = max(0, int(value))
            return f"{seconds // 3600:02d}:{seconds // 60 % 60:02d}:{seconds % 60:02d}"
        try:
            print(f"[{location} elapsed {duration(now - started)} | previous stage {duration(now - previous)}] {label}",
                  file=sys.stderr, flush=True)
        except OSError:
            # Display failure must never interrupt an owned pause/unpause sequence.
            pass
        previous = now
    return report


def capture(root_arg, name, scope="full"):
    progress = stage_reporter("source")
    progress("Checking runtime, capture lock and available space")
    require(scope in ("personal", "full"), "unsupported backup scope")
    personal = scope == "personal"
    payloads = PERSONAL_PAYLOADS if personal else PAYLOADS
    require("RESTORE_GUIDE" in globals() and "BUNDLE_SOURCE" in globals(),
            "capture requires the generated embedded program")
    root = Path(root_arg)
    require(root.is_absolute() and root == root.resolve() and root.is_dir(), "invalid runtime root")
    require(name == "hermes", "unsupported container selection")
    os.umask(0o077)
    for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP, signal.SIGALRM):
        signal.signal(signum, interrupted)
    lock_path = root / ".hermes-backup.lock"
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "r+b") as lock:
        require(stat.S_ISREG(os.fstat(lock.fileno()).st_mode), "invalid backup lock")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise BundleError("another capture is active") from None
        # Keep the lock inode: unlinking it permits overlapping holders.
        with tempfile.TemporaryDirectory(prefix=".hermes-backup-", dir=root) as tmp:
            stage = Path(tmp)
            container = inspect("container", name)
            profile = validate_container(container, root, name)
            container_id = container["Id"]
            image_id = container["Image"]
            image = inspect("image", image_id)
            require(image.get("Id") == image_id, "image inspection identity mismatch")
            require_space(root, image, personal=personal)
            diff = layer_diff(container_id)
            tag = container["Config"].get("Image") if personal else "hermes-recovery:" + image_id[7:]
            require(isinstance(tag, str) and tag, "invalid image reference")
            compose = restore_compose(container, root, tag, personal=personal)
            write_json(stage / "container-inspect.json", container)
            write_json(stage / "image-inspect.json", image)
            write_json(stage / "compose.restore.json", compose)
            (stage / "RESTORE.md").write_text(RESTORE_GUIDE, encoding="utf-8")
            (stage / "verify.py").write_text(BUNDLE_SOURCE, encoding="utf-8")
            if not personal:
                progress("Saving Docker image on source (container not paused by this capture)")
                run(["docker", "image", "save", "--output", str(stage / "image.tar"), image_id], timeout=900)
            owned_pause = False
            try:
                current = inspect("container", name)
                require(current.get("Id") == container_id and current.get("State", {}).get("Running")
                        and not current["State"].get("Paused"), "container changed before pause")
                progress("Pausing source for the state snapshot")
                # Set intent first: Docker can pause successfully then report an error.
                owned_pause = True
                run(["docker", "pause", container_id])
                current = inspect("container", name)
                require(current.get("Id") == container_id and current.get("State", {}).get("Paused")
                        and current["State"].get("Running"), "container changed during pause")
                progress("Snapshotting state on source (pause confirmed)")
                diff = layer_diff(container_id)
                if personal:
                    personal_snapshot(root, stage)
                else:
                    run(["tar", "--numeric-owner", "--acls", "--xattrs", "-cf", str(stage / "state.tar"),
                         "-C", str(root), "data", "app"], timeout=300)
                current = inspect("container", name)
                require(current.get("Id") == container_id and current.get("State", {}).get("Paused")
                        and current["State"].get("Running"), "container changed during snapshot")
                progress("Unpausing source after snapshot")
                run(["docker", "unpause", container_id])
                current = inspect("container", name)
                require(current.get("Id") == container_id and current.get("State", {}).get("Running")
                        and not current["State"].get("Paused"), "unpause could not be confirmed")
                owned_pause = False
            finally:
                if owned_pause:
                    # Cleanup is bounded and cannot be interrupted by a second signal.
                    for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP, signal.SIGALRM):
                        signal.signal(signum, signal.SIG_IGN)
                    try:
                        run(["docker", "unpause", container_id])
                    except BundleError:
                        print("hermes backup: owned unpause failed; operator intervention required", file=sys.stderr)
                    finally:
                        for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP, signal.SIGALRM):
                            signal.signal(signum, interrupted)
            progress("Source unpause confirmed; hashing snapshot and image payloads")
            signal.alarm(5400)
            manifest = {"format": PERSONAL_FORMAT if personal else FORMAT, "version": 1,
                        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                        "source": {"root": str(root), "container": name, "container_id": container_id, "profile": profile},
                        "image": {"id": image_id, "reference": container["Config"].get("Image"),
                                  "repo_digests": image.get("RepoDigests") or [], "os": image.get("Os"),
                                  "architecture": image.get("Architecture"), "restore_tag": tag},
                        "layer_diff": diff,
                        "payloads": {name: digest_file(stage / name) for name in sorted(payloads)}}
            if personal:
                del manifest["image"]["restore_tag"]
                manifest["state_policy"] = PERSONAL_POLICY
            write_json(stage / "manifest.json", manifest)
            # Stream after unpause: do not duplicate the archive or verification
            # payloads on the server. The controller verifies before publication.
            progress("Compressing and transmitting archive; source is no longer paused by this capture")
            try:
                with tarfile.open(fileobj=sys.stdout.buffer, mode="w|gz") as archive:
                    for name in ["manifest.json"] + sorted(payloads):
                        archive.add(stage / name, arcname=name, recursive=False)
                sys.stdout.buffer.flush()
                progress("Archive stream sent; controller integrity verification still required")
            finally:
                signal.alarm(0)


def safe_name(name):
    require(isinstance(name, str) and name and not name.startswith("/")
            and "\\" not in name and "\x00" not in name, "unsafe archive member path")
    path = PurePosixPath(name)
    require(".." not in path.parts, "unsafe archive member path")
    normalized = str(path)
    require(normalized not in (".", ""), "unsafe archive member path")
    return normalized


def json_member(archive, member):
    require(member.size <= SMALL_LIMIT, "metadata exceeds size limit")
    stream = archive.extractfile(member)
    require(stream is not None, "metadata is not a regular file")
    return json.load(stream)


def read_member(archive, member):
    digest, size = hashlib.sha256(), 0
    with archive.extractfile(member) as stream:
        while block := stream.read(1024 * 1024):
            size += len(block)
            digest.update(block)
    require(size == member.size, "truncated nested member")
    return "sha256:" + digest.hexdigest()


def layer_digest(archive, member):
    with archive.extractfile(member) as raw:
        magic = raw.read(4)
        raw.seek(0)
        if magic[:2] == b"\x1f\x8b":
            with gzip.GzipFile(fileobj=raw, mode="rb") as decompressed:
                digest = hashlib.sha256()
                while block := decompressed.read(1024 * 1024):
                    digest.update(block)
                return "sha256:" + digest.hexdigest()
        if magic == b"\x28\xb5\x2f\xfd":
            try:
                from compression import zstd
            except ImportError:
                raise BundleError("zstd layer verification unsupported: stdlib decoder unavailable") from None
            try:
                with zstd.ZstdFile(raw, "rb") as decompressed:
                    digest = hashlib.sha256()
                    while block := decompressed.read(1024 * 1024):
                        digest.update(block)
                    return "sha256:" + digest.hexdigest()
            except (zstd.ZstdError, EOFError, OSError):
                raise BundleError("zstd layer verification failed") from None
    return read_member(archive, member)


def zero_tail(stream):
    while block := stream.read(1024 * 1024):
        require(not block.strip(b"\x00"), "unexpected content after archive end")


def validate_state(path, profile, personal=False):
    seen, links, hardlinks = {}, set(), []
    with tarfile.open(path, "r:") as archive:
        for member in archive:
            name = safe_name(member.name)
            require(name.split("/")[0] in ("app", "data") and name not in seen,
                    "unexpected or duplicate state member")
            require(not personal or not personal_excluded(name), "excluded content in personal state")
            require(member.isfile() or member.isdir() or member.issym() or member.islnk(),
                    "unsupported state file type")
            seen[name] = member
            if member.isfile():
                read_member(archive, member)
            if member.issym():
                # Interpreter symlinks into the immutable image are legitimate.
                # Never allow an archived member underneath a symlink ancestor.
                links.add(name)
            if member.islnk():
                hardlinks.append((name, safe_name(member.linkname)))
        archive.fileobj.seek(archive.offset)
        zero_tail(archive.fileobj)
    for name in seen:
        require(not any(str(parent) in links for parent in PurePosixPath(name).parents),
                "archive member traverses a symlink")
    for name, target in hardlinks:
        require(target in seen and seen[target].isfile(), "invalid state hardlink")
    for name in ("app", "data"):
        require(name in seen and seen[name].isdir(), "required state directory missing")
    for name in ("app/docker-compose.yml", "app/gateway.env", "data/config.yaml"):
        require(name in seen and (seen[name].isfile() or seen[name].islnk()), "required state file missing")
    if profile != "default":
        name = "data/profiles/" + profile
        require(name in seen and seen[name].isdir(), "active profile state missing")


def validate_oci_identity(archive, seen, expected, config_digest, config_size, layers):
    # The archive's outer index is only a locator. Trust starts at the inspected
    # root digest and follows checked descriptors, never tags or platform alone.
    index_type = "application/vnd.oci.image.index.v1+json"
    manifest_type = "application/vnd.oci.image.manifest.v1+json"
    config_type = "application/vnd.oci.image.config.v1+json"
    layer_types = {"application/vnd.oci.image.layer.v1.tar" + suffix
                   for suffix in ("", "+gzip", "+zstd")}

    def metadata(name):
        require(name in seen and seen[name].isfile(), "OCI metadata missing")
        value = json_member(archive, seen[name])
        require(isinstance(value, dict), "invalid OCI metadata")
        return value

    def document(descriptor, allowed):
        member = checked_descriptor(descriptor, allowed)
        value = metadata(member.name)
        require(type(value.get("schemaVersion")) is int and value["schemaVersion"] == 2
                and value.get("mediaType", descriptor["mediaType"]) == descriptor["mediaType"],
                "invalid OCI document schema")
        return value

    def checked_descriptor(descriptor, allowed):
        require(isinstance(descriptor, dict) and descriptor.get("mediaType") in allowed
                and isinstance(descriptor.get("digest"), str) and HEX.fullmatch(descriptor["digest"])
                and type(descriptor.get("size")) is int and descriptor["size"] >= 0,
                "invalid OCI descriptor")
        name = "blobs/sha256/" + descriptor["digest"][7:]
        # validate_image already hashed every stored blob against its filename.
        require(name in seen and seen[name].isfile() and seen[name].size == descriptor["size"],
                "OCI descriptor blob missing or size mismatch")
        return seen[name]

    require(metadata("oci-layout").get("imageLayoutVersion") == "1.0.0", "unsupported OCI layout")
    index = metadata("index.json")
    require(type(index.get("schemaVersion")) is int and index["schemaVersion"] == 2
            and index.get("mediaType", index_type) == index_type
            and isinstance(index.get("manifests"), list), "invalid OCI archive index")
    roots = [entry for entry in index["manifests"]
             if isinstance(entry, dict) and entry.get("digest") == expected["id"]]
    require(len(roots) == 1, "saved OCI root identity missing or ambiguous")
    root = roots[0]
    image_manifest = document(root, {index_type, manifest_type})
    if root["mediaType"] == index_type:
        require(isinstance(image_manifest.get("manifests"), list), "invalid OCI image index")
        platform = {"os": expected["os"], "architecture": expected["architecture"],
                    "variant": expected.get("variant", "")}
        selected = [entry for entry in image_manifest["manifests"]
                    if isinstance(entry, dict) and isinstance(entry.get("platform"), dict)
                    and all(entry["platform"].get(key, "") == value for key, value in platform.items())]
        require(len(selected) == 1, "saved OCI platform missing or ambiguous")
        # Other platforms may legitimately be absent from Docker's content store.
        # Nested indexes and ambiguous platform selections fail closed.
        image_manifest = document(selected[0], {manifest_type})
    config_descriptor = image_manifest.get("config")
    checked_descriptor(config_descriptor, {config_type})
    require(config_descriptor["digest"] == config_digest and config_descriptor["size"] == config_size,
            "saved OCI config linkage mismatch")
    descriptors = image_manifest.get("layers")
    require(isinstance(descriptors, list) and len(descriptors) == len(layers), "saved OCI layer count mismatch")
    for name, descriptor in zip(layers, descriptors):
        member = checked_descriptor(descriptor, layer_types)
        saved = seen[safe_name(name)]
        require(saved.size == descriptor["size"] and (saved.name == member.name
                or read_member(archive, saved) == descriptor["digest"]), "saved OCI layer linkage mismatch")


def validate_image(path, expected):
    # Docker save may identify a legacy config or an OCI manifest/index root.
    # Both authenticate the exact config and ordered layers; nothing is loaded.
    with tarfile.open(path, "r:") as archive:
        seen = {}
        for member in archive:
            name = safe_name(member.name)
            require(name not in seen and (member.isfile() or member.isdir()),
                    "duplicate or unsupported image member")
            seen[name] = member
            if member.isfile() and name.startswith("blobs/sha256/"):
                require(re.fullmatch(r"blobs/sha256/[0-9a-f]{64}", name)
                        and read_member(archive, member) == "sha256:" + name.rsplit("/", 1)[1],
                        "stored image blob identity mismatch")
        require("manifest.json" in seen and seen["manifest.json"].isfile(), "image manifest missing")
        manifest = json_member(archive, seen["manifest.json"])
        require(isinstance(manifest, list) and len(manifest) == 1, "unexpected saved image count")
        item = manifest[0]
        config_name = safe_name(item["Config"])
        require(config_name in seen and seen[config_name].isfile(), "image config missing")
        config_member = seen[config_name]
        require(config_member.size <= SMALL_LIMIT, "image config exceeds size limit")
        config_bytes = archive.extractfile(config_member).read()
        config_digest = "sha256:" + hashlib.sha256(config_bytes).hexdigest()
        config = json.loads(config_bytes)
        require(config.get("os") == expected["os"] and config.get("architecture") == expected["architecture"],
                "saved image platform mismatch")
        layers = item["Layers"]
        require(isinstance(layers, list) and len(layers) == len(config.get("rootfs", {}).get("diff_ids", [])),
                "invalid image layer metadata")
        for name, diff_id in zip(layers, config["rootfs"]["diff_ids"]):
            name = safe_name(name)
            require(name in seen and seen[name].isfile(), "image layer missing")
            require(HEX.fullmatch(diff_id) and layer_digest(archive, seen[name]) == diff_id,
                    "image layer identity mismatch")
        if config_digest != expected["id"]:
            validate_oci_identity(archive, seen, expected, config_digest, len(config_bytes), layers)
            require(config.get("variant", "") == expected.get("variant", ""), "saved image variant mismatch")
        archive.fileobj.seek(archive.offset)
        zero_tail(archive.fileobj)


@contextmanager
def verified_bundle(bundle, scope=None, progress=None):
    progress = progress or (lambda label: None)
    progress("Decompressing archive and checking payload hashes")
    require(scope in (None, "personal", "full"), "unsupported backup scope")
    # A private staging copy bounds memory regardless of state/image size. It
    # writes opaque tar bytes only, never extracts caller-controlled filenames.
    os.umask(0o077)
    with tempfile.TemporaryDirectory(prefix="hermes-verify-") as tmp:
        stage = Path(tmp)
        seen, hashes, metadata = set(), {}, {}
        with gzip.GzipFile(bundle, "rb") as compressed:
            with tarfile.open(fileobj=compressed, mode="r|") as archive:
                for member in archive:
                    name = safe_name(member.name)
                    require(name in PAYLOADS | {"manifest.json"} and member.name == name and member.isfile()
                            and name not in seen, "unexpected, duplicate or nonregular bundle member")
                    seen.add(name)
                    require(member.size >= 0, "invalid member size")
                    if name not in ("state.tar", "image.tar"):
                        require(member.size <= SMALL_LIMIT, "metadata exceeds size limit")
                    digest, size = hashlib.sha256(), 0
                    stream = archive.extractfile(member)
                    assert stream is not None  # Only regular members admitted above.
                    with (stage / name).open("wb") as out:
                        while block := stream.read(1024 * 1024):
                            size += len(block)
                            digest.update(block)
                            out.write(block)
                    require(size == member.size, "truncated bundle member")
                    hashes[name] = {"sha256": digest.hexdigest(), "size": size}
                zero_tail(archive.fileobj)
            # Drain gzip to require CRC/footer validation, including truncation.
            while compressed.read(1024 * 1024):
                pass
        for name in ("manifest.json", "container-inspect.json", "image-inspect.json", "compose.restore.json"):
            metadata[name] = json.loads((stage / name).read_bytes())
        manifest = metadata["manifest.json"]
        require(manifest.get("format") in (FORMAT, PERSONAL_FORMAT) and type(manifest.get("version")) is int
                and manifest["version"] == 1, "unsupported recovery bundle schema")
        personal = manifest["format"] == PERSONAL_FORMAT
        require(scope is None or scope == ("personal" if personal else "full"), "backup scope mismatch")
        payloads = PERSONAL_PAYLOADS if personal else PAYLOADS
        require(seen == payloads | {"manifest.json"}, "required or unexpected bundle member")
        if personal:
            policy = manifest.get("state_policy")
            require(isinstance(policy, dict) and type(policy.get("version")) is int
                    and policy == PERSONAL_POLICY, "unsupported personal state policy")
        require(set(manifest["payloads"]) == payloads and all(isinstance(manifest["payloads"][name], dict)
                and type(manifest["payloads"][name].get("size")) is int
                and manifest["payloads"][name] == hashes[name] for name in payloads), "payload integrity mismatch")
        require(isinstance(manifest.get("created_at"), str)
                and datetime.datetime.fromisoformat(manifest["created_at"]).tzinfo is not None,
                "invalid creation time")
        source, image = manifest["source"], manifest["image"]
        require(isinstance(source["root"], str) and source["root"].startswith("/")
                and source["container"] == "hermes" and re.fullmatch(r"[0-9a-f]{64}", source["container_id"])
                and re.fullmatch(r"[A-Za-z0-9_-]+", source["profile"]), "invalid source metadata")
        require(HEX.fullmatch(image["id"]) and ((personal and "restore_tag" not in image)
                or (not personal and image["restore_tag"] == "hermes-recovery:" + image["id"][7:]))
                and isinstance(image["reference"], str) and image["reference"]
                and isinstance(image["repo_digests"], list) and image["os"] == "linux"
                and isinstance(image["architecture"], str) and image["architecture"], "invalid image metadata")
        container, inspected_image = metadata["container-inspect.json"], metadata["image-inspect.json"]
        require(container.get("Image") == image["id"] and container.get("Id") == source["container_id"]
                and container.get("Name") == "/hermes" and profile_for(container) == source["profile"]
                and container["Config"].get("Image") == image["reference"], "container metadata mismatch")
        require(inspected_image.get("Id") == image["id"] and inspected_image.get("Os") == image["os"]
                and inspected_image.get("Architecture") == image["architecture"]
                and (inspected_image.get("RepoDigests") or []) == image["repo_digests"], "image metadata mismatch")
        restore_image = image["reference"] if personal else image["restore_tag"]
        require(metadata["compose.restore.json"] == restore_compose(container, Path(source["root"]), restore_image,
                                                                   personal=personal), "restore configuration mismatch")
        require((stage / "RESTORE.md").stat().st_size > 0 and (stage / "verify.py").stat().st_size > 0,
                "empty recovery instructions or verifier")
        progress("Checking state archive structure and recovery metadata")
        validate_state(stage / "state.tar", source["profile"], personal=personal)
        if not personal:
            progress("Checking saved Docker image identity and layer hashes")
            validate_image(stage / "image.tar", dict(image, variant=inspected_image.get("Variant") or ""))
        yield stage, manifest


def verify(bundle, scope=None, progress=None):
    with verified_bundle(bundle, scope, progress) as (_, manifest):
        return manifest


def restore_state(bundle, destination):
    """Restore trusted bytes only; never load images, run hooks or start services.

    GNU tar retains numeric owners/ACLs/xattrs. Use a new compatible Linux target
    and a trusted private parent; failures retain a partial destination for
    inspection and must never be treated as a completed restore.
    """
    os.umask(0o077)
    require(destination.is_absolute() and destination.parent.is_dir()
            and destination.parent == destination.parent.resolve(),
            "restore destination needs an absolute path and a real existing parent")
    require(not os.path.lexists(destination), "restore destination already exists")
    require(b"GNU tar" in run(["tar", "--version"]), "restore requires GNU tar on compatible Linux")
    with verified_bundle(bundle) as (stage, manifest):
        destination.mkdir(mode=0o700)  # exclusive; refuse a concurrently created target
        recovery = destination / ".recovery"
        # Consume only the checked private payloads, never reopen the source.
        shutil.move(str(stage), recovery)
        run(["tar", "--extract", "--file", str(recovery / "state.tar"),
             "--directory", str(destination), "--numeric-owner", "--same-owner",
             "--same-permissions", "--acls", "--xattrs", "--xattrs-include=*"],
            timeout=5400, reject_diagnostics=True)
        # Compare bytes/basic stat metadata. GNU tar does not compare ACL/xattr
        # values; extraction warnings above fail closed, but are not readback.
        run(["tar", "--compare", "--file", str(recovery / "state.tar"),
             "--directory", str(destination), "--numeric-owner"],
            timeout=5400, reject_diagnostics=True)
    return manifest


def main():
    try:
        args = sys.argv[1:]
        if len(args) == 2 and args[0] == "program":
            source = Path(__file__).read_bytes().decode("utf-8")
            guide = Path(args[1]).read_bytes().decode("utf-8")
            require(bool(guide), "restore guide is empty")
            sys.stdout.write("RESTORE_GUIDE = " + repr(guide) + "\nBUNDLE_SOURCE = " + repr(source) + "\n" + source)
        elif len(args) in (3, 4) and args[0] == "capture":
            capture(args[1], args[2], args[3] if len(args) == 4 else "full")
        elif len(args) == 3 and args[0] == "restore-state":
            restore_state(Path(args[1]), Path(args[2]))
            print("Archive verified; state extracted and compared. Runtime NOT started or verified.")
        elif len(args) in (2, 3) and args[0] in ("verify", "verify-progress"):
            progress = stage_reporter("verification") if args[0] == "verify-progress" else None
            manifest = verify(Path(args[1]), args[2] if len(args) == 3 else None, progress=progress)
            if manifest["format"] == PERSONAL_FORMAT:
                print("Personal bundle integrity and retained state verified; reinstall/restore not tested.")
            else:
                print("Recovery bundle integrity and structure verified; restore not tested.")
        else:
            raise BundleError("usage: helper program GUIDE | capture ROOT hermes [personal] | verify BUNDLE.tar.gz [personal|full] | verify-progress BUNDLE.tar.gz [personal|full] | restore-state BUNDLE.tar.gz NEW_ABSOLUTE_DIRECTORY")
        return 0
    except BundleError as error:
        # BundleError messages are fixed developer strings, never runtime data.
        print("hermes backup: " + str(error), file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError, TypeError, AttributeError, tarfile.TarError, EOFError):
        # Never stringify external exceptions: they can contain credentials.
        print("hermes backup: operation failed (invalid, unsupported, interrupted, or incomplete bundle/runtime)", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
