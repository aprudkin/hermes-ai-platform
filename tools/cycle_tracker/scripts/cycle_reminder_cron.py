#!/usr/bin/env python3
"""Hermes no-agent entrypoint. Due messages go only through the runner's outbox."""
import runpy
import sys
from pathlib import Path
sys.dont_write_bytecode = True
runner = Path(__file__).with_name('cycle_reminder_runner.py')
sys.argv = [str(runner), '--execute', *sys.argv[1:]]
runpy.run_path(str(runner), run_name='__main__')
