#!/usr/bin/env python3
"""Copy an existing full bundle through the owner's Mail.ru crypt configuration."""

import configparser
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile


REMOTE = "hermes-backup:full/"
CRYPT_ROOT = "mailru-hermes:Hermes-Backups/crypt-v1"
HELPER = Path(__file__).resolve().with_name("hermes_backup_bundle.py")


class CloudError(Exception):
    pass


def require(condition, message):
    if not condition:
        raise CloudError(message)


def private_copy(source, destination, label, max_size=None):
    """Open once, reject symlinks/special files, and copy without exposing paths."""
    require(source.is_absolute(), f"{label} must be an absolute path")
    fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as incoming:
        info = os.fstat(incoming.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                and not stat.S_IMODE(info.st_mode) & 0o077,
                f"{label} must be an owner-only regular file owned by this user")
        require(max_size is None or info.st_size <= max_size, f"{label} is too large")
        with destination.open("xb") as outgoing:
            shutil.copyfileobj(incoming, outgoing, length=1024 * 1024)


def read_config(path, crypt_root=CRYPT_ROOT, directory_name_encryption="true"):
    config = configparser.ConfigParser(interpolation=None)
    with path.open() as stream:
        config.read_file(stream)
    require(not config.defaults() and set(config.sections()) == {"hermes-backup", "mailru-hermes"},
            "configuration must contain only the two dedicated Hermes remotes")
    crypt = dict(config["hermes-backup"])
    transport = dict(config["mailru-hermes"])
    require(set(crypt) == {"type", "remote", "filename_encryption",
                           "directory_name_encryption", "password", "password2"},
            "unsupported crypt configuration options")
    require(crypt["type"] == "crypt" and crypt["remote"] == crypt_root
            and crypt["filename_encryption"] == "standard"
            and crypt["directory_name_encryption"] == directory_name_encryption
            and crypt["password"] and crypt["password2"],
            "expected encrypted Hermes remote and both recovery keys")
    require(set(transport) == {"type", "url", "vendor", "user", "pass"},
            "unsupported transport configuration options")
    require(transport["type"] == "webdav"
            and transport["url"] in ("https://webdav.cloud.mail.ru", "https://webdav.cloud.mail.ru/")
            and transport["vendor"] == "other" and transport["user"] and transport["pass"],
            "expected authenticated HTTPS Mail.ru WebDAV transport")
    return crypt, transport


def run_checked(command, env, phase):
    print(phase, file=sys.stderr, flush=True)
    try:
        result = subprocess.run(command, env=env, stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                timeout=5400, check=False)
    except subprocess.TimeoutExpired:
        raise CloudError(f"{phase}: timed out; no verification success claimed") from None
    require(result.returncode == 0, f"{phase}: failed; private command output suppressed")


def digest(path):
    checksum = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


def execute():
    require(os.environ.get("HERMES_CONFIRM_CLOUD_UPLOAD") == "1",
            "set HERMES_CONFIRM_CLOUD_UPLOAD=1 only after authorizing this Mail.ru upload/readback")
    archive_value = os.environ.get("HERMES_BACKUP_FILE", "")
    require(archive_value, "set HERMES_BACKUP_FILE to an existing trusted full bundle")
    archive = Path(archive_value)
    require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*\.tar\.gz", archive.name),
            "archive basename must use ASCII letters, digits, dots, underscores or hyphens and end in .tar.gz")
    config = Path(os.environ.get("HERMES_CLOUD_CONFIG", str(Path.home() / ".config/rclone/hermes-backup.conf")))
    recovery = Path(os.environ.get("HERMES_CLOUD_RECOVERY_CONFIG", str(Path.home() / "backup/hermes-recovery-kit/rclone.conf")))
    require(config.resolve() != recovery.resolve(), "recovery configuration must be a separately saved file")
    rclone = shutil.which("rclone")
    require(rclone is not None, "rclone is required; no tools will be installed automatically")
    # Never inherit remote overrides, password commands, log destinations or TLS switches.
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith("RCLONE_")}
    remote = REMOTE + archive.name
    with tempfile.TemporaryDirectory(prefix="hermes-cloud-") as directory:
        stage = Path(directory)
        env["TMPDIR"] = str(stage)
        working_config = stage / "upload.conf"
        recovery_config = stage / "recovery.conf"
        private_copy(config, working_config, "working config", 65536)
        private_copy(recovery, recovery_config, "recovery config", 65536)
        require(read_config(working_config) == read_config(recovery_config),
                "working and recovery configurations differ; reconcile the recovery kit first")
        # Directory-mode rclone copy enforces --immutable. Single-file copy/copyto
        # can bypass it. This directory must contain ONLY the archive, never configs.
        upload_directory = stage / "upload"
        upload_directory.mkdir(mode=0o700)
        source = upload_directory / archive.name
        downloaded = stage / "downloaded.tar.gz"
        private_copy(archive, source, "archive")
        run_checked([sys.executable, str(HELPER), "verify", str(source), "full"], env,
                    "Verify private full-bundle snapshot before upload")
        checksum = digest(source)
        # size-only prevents timestamp reconciliation on an existing object. A same-size
        # collision is not trusted: download + SHA-256 + bundle verification below decide.
        flags = ["--immutable", "--size-only", "--retries", "1", "--low-level-retries", "3",
                 "--contimeout", "30s", "--timeout", "5m", "--stats", "0", "--log-level", "ERROR"]
        run_checked([rclone, "copy", str(upload_directory), REMOTE, "--config", str(working_config), *flags],
                    env, "Upload through crypt (copy-only, immutable)")
        run_checked([rclone, "copyto", remote, str(downloaded), "--config", str(recovery_config), *flags],
                    env, "Download and decrypt through saved recovery config")
        require(downloaded.is_file() and downloaded.stat().st_size == source.stat().st_size
                and digest(downloaded) == checksum, "downloaded archive size or SHA-256 mismatch")
        run_checked([sys.executable, str(HELPER), "verify", str(downloaded), "full"], env,
                    "Verify downloaded full bundle")
        result = {"remote": remote, "bytes": source.stat().st_size, "sha256": checksum,
                  "recovery_config_used": True, "bundle_integrity_verified": True,
                  "state_restored": False, "restored_runtime_verified": False}
    print(json.dumps(result, sort_keys=True))


def interrupted(_number, _frame):
    raise CloudError("interrupted; remote object may exist but is not confirmed verified")


def main():
    os.umask(0o077)
    signal.signal(signal.SIGTERM, interrupted)
    if sys.argv[1:] == ["--help"]:
        print("Upload an existing full bundle to Mail.ru crypt and verify a recovery-config download.\n"
              "Requires HERMES_BACKUP_FILE (absolute path) and HERMES_CONFIRM_CLOUD_UPLOAD=1.\n"
              "Optional absolute config paths: HERMES_CLOUD_CONFIG, HERMES_CLOUD_RECOVERY_CONFIG.\n"
              "No capture, restore, deletion, scheduling or installation. See docs/cloud-backup.md.")
        return 0
    try:
        require(not sys.argv[1:], "no command-line arguments supported except --help")
        execute()
    except CloudError as error:
        print(f"Cloud backup failed: {error}", file=sys.stderr)
        return 1
    except (OSError, ValueError, configparser.Error, KeyboardInterrupt):
        # Exceptions and rclone diagnostics can contain credentials or private filenames.
        print("Cloud backup failed: local input/I/O/configuration error or interruption; "
              "no verified result claimed. Check private inputs and available disk space.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
