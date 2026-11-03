"""Resolve a cash calculation with append-only provenance, never a new accrual."""
import json
from datetime import datetime, timezone
import importlib.util
import sys
from pathlib import Path


def apply_correction(ledger, *, source_row_id, resolution_row_id, reason):
    spec = importlib.util.spec_from_file_location('cash_correction_parser', Path(__file__).with_name('cash_ledger_monitor.py'))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    with ledger._connection() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS calculation_corrections(
            source_row_id INTEGER NOT NULL, resolution_row_id INTEGER NOT NULL,
            created_at TEXT NOT NULL, reason TEXT NOT NULL,
            before_json TEXT NOT NULL, after_json TEXT NOT NULL,
            PRIMARY KEY(source_row_id,resolution_row_id))''')
        existing = c.execute('SELECT after_json FROM calculation_corrections WHERE source_row_id=? AND resolution_row_id=?',
                             (source_row_id,resolution_row_id)).fetchone()
        if existing:
            return json.loads(existing['after_json'])
        row = c.execute('SELECT * FROM messages WHERE source_row_id=?',(source_row_id,)).fetchone()
        if row is None:
            raise ValueError('Source cash report not found')
        parsed = module.parse_message(row['raw_content'])
        total = sum(e.amount_minor for e in parsed.entries)
        if parsed.review_lines or parsed.claimed_total_minor is None or total != parsed.claimed_total_minor:
            raise ValueError('Correction is not an unambiguous verified total')
        before = {'message':dict(row), 'entries':[dict(r) for r in c.execute('SELECT * FROM entries WHERE source_row_id=? ORDER BY line_no',(source_row_id,))],
                  'reviews':[dict(r) for r in c.execute('SELECT * FROM parse_reviews WHERE source_row_id=?',(source_row_id,))]}
        after = {'computed_total_minor':total,'claimed_total_minor':parsed.claimed_total_minor,
                 'difference_minor':0,'check_status':'ok',
                 'entries':[{'label':e.label,'amount_minor':e.amount_minor} for e in parsed.entries]}
        c.execute('INSERT INTO calculation_corrections VALUES(?,?,?,?,?,?)',
                  (source_row_id,resolution_row_id,datetime.now(timezone.utc).isoformat(),reason,
                   json.dumps(before,ensure_ascii=False),json.dumps(after,ensure_ascii=False)))
        c.execute('DELETE FROM entries WHERE source_row_id=?',(source_row_id,))
        c.executemany('INSERT INTO entries(source_row_id,line_no,label,amount_minor) VALUES(?,?,?,?)',
                      [(source_row_id,n,e.label,e.amount_minor) for n,e in enumerate(parsed.entries,1)])
        c.execute("UPDATE messages SET computed_total_minor=?,difference_minor=0,check_status='ok' WHERE source_row_id=?",(total,source_row_id))
        return after
