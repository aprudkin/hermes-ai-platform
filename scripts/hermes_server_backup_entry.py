#!/usr/bin/env python3
"""Isolated-Python entry point for the fixed, root-owned installed package."""
import sys

sys.path.insert(0, '/usr/local/lib/hermes-backup')
from hermes_server_backup import main

if __name__ == '__main__':
    sys.exit(main())
