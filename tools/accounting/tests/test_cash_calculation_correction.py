import unittest
import tempfile
from pathlib import Path
import importlib.util
from test_cash_ledger_monitor import load_module
from test_cash_qv import REPORT

class CorrectionTests(unittest.TestCase):
    def test_resolves_derived_check_preserves_raw_and_old_calculation(self):
        path=Path(__file__).resolve().parents[1]/'scripts'/'cash_calculation_correction.py'
        spec=importlib.util.spec_from_file_location('correction',path)
        helper=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        m=load_module()
        with tempfile.TemporaryDirectory() as tmp:
            ledger=m.Ledger(Path(tmp)/'ledger.db')
            ledger.process_message(source_row_id=1,timestamp=1791337604.0,
                platform_message_id='99',content=REPORT)
            with ledger._connection() as c:
                c.execute('DELETE FROM entries WHERE source_row_id=1 AND amount_minor=17000')
                c.execute("UPDATE messages SET check_status='unverified',computed_total_minor=NULL,difference_minor=NULL WHERE source_row_id=1")
                c.execute("INSERT INTO parse_reviews VALUES(1,1,'qv/170')")
            helper.apply_correction(ledger,source_row_id=1,resolution_row_id=2,reason='Owner confirmed qv/170')
            helper.apply_correction(ledger,source_row_id=1,resolution_row_id=2,reason='Owner confirmed qv/170')
            with ledger._connection() as c:
                row=c.execute('SELECT * FROM messages WHERE source_row_id=1').fetchone()
                self.assertEqual(row['raw_content'],REPORT)
                self.assertEqual(row['computed_total_minor'],57000)
                self.assertEqual(row['check_status'],'ok')
                self.assertEqual(c.execute('SELECT COUNT(*) FROM calculation_corrections').fetchone()[0],1)
                self.assertIn('unverified',c.execute('SELECT before_json FROM calculation_corrections').fetchone()[0])
                self.assertEqual(c.execute('SELECT COUNT(*) FROM parse_reviews').fetchone()[0],1)
            self.assertEqual(ledger.model_statistics(),{'Fixture':40000})
            self.assertEqual(ledger.agency_statistics(),{'Fixture':17000})
