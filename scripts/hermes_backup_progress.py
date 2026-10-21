#!/usr/bin/env python3
"""Local backup progress on stderr; stdout remains the unchanged archive stream."""
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import time

HELPER = Path(__file__).resolve().with_name("hermes_backup_bundle.py")


def clock(seconds):
    seconds = max(0, int(seconds))
    return f"{seconds // 3600:02d}:{seconds // 60 % 60:02d}:{seconds % 60:02d}"


def report(start, elapsed, message):
    print(f"[elapsed {clock(elapsed + time.monotonic() - start)}] {message}",
          file=sys.stderr, flush=True)


def receive(interval=5, elapsed=0):
    start = previous_time = time.monotonic()
    received = previous_bytes = 0
    report(start, elapsed, "Connecting to source; server stage messages will follow")
    while True:
        readable, _, _ = select.select([sys.stdin], [], [], max(0, previous_time + interval - time.monotonic()))
        if readable:
            block = os.read(sys.stdin.fileno(), 1024 * 1024)
            if not block:
                report(start, elapsed, f"Stream ended: {received / 1048576:.1f} MiB received; integrity check pending")
                return
            sys.stdout.buffer.write(block)
            sys.stdout.buffer.flush()
            received += len(block)
        now = time.monotonic()
        if now - previous_time >= interval:
            rate = (received - previous_bytes) / (now - previous_time) / 1048576
            if received:
                report(start, elapsed, f"Receiving: {received / 1048576:.1f} MiB | {rate:.2f} MiB/s (last interval)")
            else:
                report(start, elapsed, "Waiting on source; see latest [source] stage above (no archive bytes yet)")
            previous_time, previous_bytes = now, received


def verify(archive, scope, interval=5, elapsed=0):
    start = time.monotonic()
    report(start, elapsed, "Verifying archive locally (hashes, state and image); no restore")
    # Keep the existing verifier and its exit status as the publication gate.
    child = subprocess.Popen([sys.executable, str(HELPER), "verify-progress", archive, scope])
    try:
        while True:
            try:
                code = child.wait(timeout=interval)
                return code if code >= 0 else 128 - code
            except subprocess.TimeoutExpired:
                report(start, elapsed, f"Verifying archive locally | verification time {clock(time.monotonic() - start)}")
    finally:
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


def interrupt(_number, _frame):
    raise KeyboardInterrupt


def main():
    signal.signal(signal.SIGTERM, interrupt)
    try:
        args = sys.argv[1:]
        if len(args) == 2 and args[0] == "receive":
            receive(elapsed=int(args[1]))
            return 0
        if len(args) == 4 and args[0] == "verify" and args[2] in ("personal", "full"):
            return verify(args[1], args[2], elapsed=int(args[3]))
        print("usage: backup progress receive ELAPSED_SECONDS | verify ARCHIVE personal|full ELAPSED_SECONDS", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Backup progress interrupted; no completed backup claimed", file=sys.stderr)
        return 130
    except (OSError, ValueError):
        print("Backup progress failed: local I/O or invalid arguments", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
