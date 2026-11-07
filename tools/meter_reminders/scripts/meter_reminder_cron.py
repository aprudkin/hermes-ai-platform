#!/usr/bin/env python3
"""Preserved entry point; read-only by default, forwarding explicit CLI options."""
from meter_reminder import main

if __name__ == '__main__':
    raise SystemExit(main())
