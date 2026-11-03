import importlib.util
import io
import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing, redirect_stdout
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "cash_ledger_monitor.py"


def load_module():
    spec = importlib.util.spec_from_file_location("cash_ledger_monitor", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class CashLedgerMonitorTests(unittest.TestCase):
    def test_model_share_is_saved_separately_without_inflating_revenue(self):
        module = load_module()
        content = (
            "Касса ❤️ SampleModel ❤️\n03.10\n"
            "1️⃣ ✅Клиент 10:00 Hr/500\nCash\n"
            "2️⃣ ✅Клиент 11:00 Hr/500\nCash\n"
            "3️⃣ ✅Клиент 21:00 Hhr/400\nCash\n"
            "Итого: 1400\nМодели: 840\nАгентских: 560\nОператор Анна: 50"
        )
        with tempfile.TemporaryDirectory() as tmp:
            ledger = module.Ledger(Path(tmp) / "ledger.db")
            result = ledger.process_message(source_row_id=1, timestamp=1791000000.0,
                                            platform_message_id="1", content=content)
            self.assertEqual(result.computed_total_minor, 140000)
            self.assertEqual(ledger.model_statistics(), {"SampleModel": 84000})
            self.assertEqual(ledger.operator_statistics(), {"Анна": 5000})
            self.assertEqual(ledger.statistics()["models"], {"SampleModel": 84000})
            ledger.process_message(source_row_id=1, timestamp=1791000000.0,
                                   platform_message_id="1", content=content)
            self.assertEqual(ledger.model_statistics(), {"SampleModel": 84000})

    def test_model_payout_has_separate_checkpoint_and_latest_report_per_day(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            ledger = module.Ledger(Path(tmp) / "ledger.db")
            for row_id, date, amount in [(1, "03.10", 800), (2, "03.10", 840)]:
                ledger.process_message(source_row_id=row_id, timestamp=1791000000.0,
                    platform_message_id=str(row_id), content=f"Касса SampleModel\n{date}\nКлиент Hr/1400\nИтого: 1400\nМодели: {amount}\nОператор Анна: 50")
            self.assertEqual(ledger.model_statistics(), {"SampleModel": 84000})
            first = ledger.create_model_payout(model_name="samplemodel", command_source_row_id=3,
                command_timestamp=1791000000.0, requester_id="1", requester_name="Test")
            self.assertEqual(first.by_date, (("2026-10-03", 84000),))
            self.assertEqual(first.total_minor, 84000)
            self.assertIn("Итого к выдаче: $840.00", first.report)
            repeat = ledger.create_model_payout(model_name="SampleModel", command_source_row_id=3,
                command_timestamp=1791000000.0, requester_id="1", requester_name="Test")
            self.assertEqual(repeat.status, "existing")
            second = ledger.create_model_payout(model_name="SampleModel", command_source_row_id=4,
                command_timestamp=1791000000.0, requester_id="1", requester_name="Test")
            self.assertEqual(second.total_minor, 0)
            self.assertEqual(ledger.operator_statistics(), {"Анна": 5000})

    def test_total_aliases_keep_model_share_below_the_revenue_boundary(self):
        module = load_module()
        for total_word in ["Total", "Итого", "Итог", "Тотал", "TOTAL"]:
            with self.subTest(total_word=total_word):
                parsed = module.parse_message(
                    f"Касса SampleModel\n03.10\nКлиент Hr/1400\n{total_word}: 1400\nМодели: 840\nОператор Анна: 50")
                self.assertEqual(parsed.claimed_total_minor, 140000)
                self.assertEqual(parsed.model_amount_minor, 84000)
                self.assertEqual(sum(e.amount_minor for e in parsed.entries), 140000)
        parsed = module.parse_message("PROFIT REGISTER Fixture\nClient Hr/900\nTotal: 900\nYours: 540\nTester Operator +40")
        self.assertEqual(parsed.model_amount_minor, 54000)

    def test_existing_reports_gain_model_shares_without_reingestion(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.db"
            ledger = module.Ledger(path)
            ledger.process_message(source_row_id=1, timestamp=1791000000.0,
                platform_message_id="1", content="Касса SampleModel\n03.10\nКлиент Hr/1400\nИтого: 1400\nМодели: 840\nОператор Анна: 50")
            with closing(sqlite3.connect(path)) as c:
                c.execute("DELETE FROM models")
                c.commit()
            migrated = module.Ledger(path)
            self.assertEqual(migrated.model_statistics(), {"SampleModel": 84000})
            self.assertEqual(migrated.register_statistics(), {"SampleModel": 140000})
            self.assertEqual(migrated.operator_statistics(), {"Анна": 5000})

    def test_cash_notice_includes_running_shares_and_current_agency_fee(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            ledger = module.Ledger(Path(tmp) / "ledger.db")
            for row_id, date, revenue, model_amount, fee in [(1,"01.10",1000,600,50),(2,"02.10",1500,900,60),(3,"03.10",1400,840,50)]:
                ledger.process_message(source_row_id=row_id, timestamp=1791000000.0,
                    platform_message_id=str(row_id), content=f"Касса SampleModel\n{date}\nКлиент Hr/{revenue}\nИтого: {revenue}\nМодели: {model_amount}\nАгентских: {revenue-model_amount}\nОператор Анна: {fee}")
            self.assertEqual(ledger.cash_notice(3),
                "**03.10 (сб):**\n"
                "✅ Итого: 1,400$ — сходится ✅\n"
                "🫦 SampleModel: 2,340$ — с 01.10 (чт) (выплат ещё не было)\n"
                "🥷🏻 Анна: 160$ — с 01.10 (чт) (выплат ещё не было)\n"
                "🎩 Агентство: 1,560$ — с 01.10 (чт) (выплат ещё не было) ✅")
            with ledger._connection() as c:
                self.assertEqual(c.execute("SELECT agency_amount_minor FROM messages WHERE source_row_id=3").fetchone()[0], 56000)
            ledger.create_model_payout(model_name="SampleModel",command_source_row_id=4,
                command_timestamp=1791000000.0,requester_id="1",requester_name="Test")
            ledger.process_message(source_row_id=5,timestamp=1791100000.0,platform_message_id="5",
                content="Касса SampleModel\n04.10\nКлиент Hr/500\nИтого: 500\nМодели: 300\nАгентских: 200\nОператор Анна: 10")
            notice = ledger.cash_notice(5)
            self.assertIn("SampleModel: 300$ — с выплаты 03.10 (сб)",notice)
            self.assertIn("Анна: 170$ — с 01.10 (чт) (выплат ещё не было)",notice)
            self.assertTrue(notice.endswith("Агентство: 200$ — с выплаты 03.10 (сб) ✅"))

    def test_model_payout_closes_agency_on_the_same_date_but_not_operator(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            ledger = module.Ledger(Path(tmp) / "ledger.db")
            for row_id, name, fee in [(1,"SampleModel",400),(2,"SampleModel",560),(3,"Fixture",360)]:
                ledger.process_message(source_row_id=row_id,timestamp=1791000000.0,platform_message_id=str(row_id),
                    content=f"Касса {name}\n0{row_id}.10\nКлиент Hr/1400\nИтого: 1400\nМодели: 840\nАгентских: {fee}\nОператор Анна: 50")
            first = ledger.create_model_payout(model_name="SampleModel",command_source_row_id=4,
                command_timestamp=1791000000.0,requester_id="1",requester_name="Test")
            self.assertEqual(first.total_minor,168000)
            with ledger._connection() as c:
                agency = c.execute("SELECT total_minor,command_timestamp FROM agency_payouts WHERE command_source_row_id=4").fetchone()
                self.assertIsNotNone(agency)
                self.assertEqual(agency["total_minor"],96000)
                self.assertEqual(agency["command_timestamp"],1791000000.0)
            repeated = ledger.create_model_payout(model_name="SampleModel",command_source_row_id=4,
                command_timestamp=1791000000.0,requester_id="1",requester_name="Test")
            self.assertEqual(repeated.status,"existing")
            ledger.process_message(source_row_id=5,timestamp=1791100000.0,platform_message_id="5",
                content="Касса SampleModel\n04.10\nКлиент Hr/500\nИтого: 500\nМодели: 300\nАгентских: 200\nОператор Анна: 10")
            notice=ledger.cash_notice(5)
            self.assertIn("Агентство: 200$ — с выплаты 03.10 (сб)",notice)
            self.assertIn("SampleModel: 300$ — с выплаты 03.10 (сб)",notice)
            self.assertIn("Анна: 160$",notice)
            second=ledger.create_model_payout(model_name="SampleModel",command_source_row_id=6,
                command_timestamp=1791100000.0,requester_id="1",requester_name="Test")
            self.assertEqual(second.total_minor,30000)
            self.assertEqual(ledger.agency_statistics(),{"Fixture":36000,"SampleModel":116000})

    def test_parse_register_message_extracts_name_pre_total_amounts_and_operator(self):
        module = load_module()
        parsed = module.parse_message(
            "[Fixture Reporter|810000003]\n"
            "Касса ❤️ SampleModel ❤️\n\n"
            "02.02\n\n"
            "1️⃣ ✅Клиент 9:05 Hr/80(депозит) +170\n"
            "2️⃣ ✅Клиент 12:05 Hhr/0\n"
            "3️⃣ ✅Клиент 15:05 Hr/230\n\n"
            "Итого: 480\n"
            "Из них:\n"
            "(80) CashApp\n(170) CashApp\n(230) Cash\n"
            "Модели: 290\nАгентских: 190\nОператор Анна: 11"
        )

        self.assertEqual(parsed.register_name, "SampleModel")
        self.assertEqual([entry.amount_minor for entry in parsed.entries], [8000, 17000, 0, 23000])
        self.assertEqual(parsed.claimed_total_minor, 48000)
        self.assertEqual(
            [(operator.name, operator.amount_minor) for operator in parsed.operators],
            [("Анна", 1100)],
        )

    def test_parse_english_register_normalizes_name_and_operator(self):
        module = load_module()
        parsed = module.parse_message(
            "[Fixture Reporter|810000003]\n"
            "PROFIT REGISTER Fixture\n\nFixture City\n03.02.2026\n\n"
            "1️⃣Client 12pm Hr/175✅cash✅\n"
            "2️⃣Client 3:05pm Hr/175✅cash✅\n\n"
            "Total: 350\n\nYours: 210\nAgent fees: 140\n\n"
            "Tester Operator +13💸💸💸"
        )

        self.assertEqual(parsed.register_name, "Fixture")
        self.assertEqual([entry.amount_minor for entry in parsed.entries], [17500, 17500])
        self.assertEqual(parsed.claimed_total_minor, 35000)
        self.assertEqual(
            [(operator.name, operator.amount_minor) for operator in parsed.operators],
            [("Tester", 1300)],
        )

    def test_ledger_keeps_separate_register_totals_and_operator_statistics(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            ledger = module.Ledger(Path(tmp) / "ledger.db")
            ledger.process_message(
                source_row_id=1,
                timestamp=1790812800.0,
                platform_message_id="1",
                content=(
                    "[Sender|1]\nКасса ❤️ SampleModel ❤️\n01.10\n"
                    "Клиент Hr/100 +400\nКлиент Hr/500\nИтого: 1000\n"
                    "Оператор Анна: 50"
                ),
            )
            ledger.process_message(
                source_row_id=2,
                timestamp=1790812860.0,
                platform_message_id="2",
                content=(
                    "[Sender|1]\nКасса 🔸💎SAMPLEB💎🔸\n01.10\n"
                    "Итого: 0\nОператор Анна: 20"
                ),
            )
            ledger.process_message(
                source_row_id=3,
                timestamp=1790812920.0,
                platform_message_id="3",
                content=(
                    "[Sender|1]\nPROFIT REGISTER Fixture\n01.10.2026\n"
                    "Client Hr/450\nClient Hr/450\nTotal: 900\n"
                    "Tester Operator +40"
                ),
            )

            self.assertEqual(
                ledger.register_statistics(),
                {"Fixture": 90000, "Sampleb": 0, "SampleModel": 100000},
            )
            self.assertEqual(
                ledger.operator_statistics(),
                {"Tester": 4000, "Анна": 7000},
            )

            operator_report = ledger.operator_report()
            self.assertIn("Tester: $40.00", operator_report)
            self.assertIn("Анна: $70.00", operator_report)
            self.assertIn("Итого операторам: $110.00", operator_report)

    def test_register_message_uses_its_stated_accounting_date(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            ledger = module.Ledger(Path(tmp) / "ledger.db")
            ledger.process_message(
                source_row_id=1,
                timestamp=1790904800.0,
                platform_message_id="1",
                content=(
                    "[Sender|1]\nКасса SampleModel\n01.10\n"
                    "Клиент Hr/1000\nИтого: 1000\nОператор Анна: 50"
                ),
            )

            self.assertEqual(ledger.daily_total_minor("2026-10-01"), 100000)
            self.assertEqual(ledger.daily_total_minor("2026-10-02"), 0)

    def test_operator_payout_reports_daily_amounts_and_starts_a_new_period(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            ledger = module.Ledger(Path(tmp) / "ledger.db")

            def add_report(row_id, heading, date, operator, amount):
                ledger.process_message(
                    source_row_id=row_id,
                    timestamp=1790904800.0,
                    platform_message_id=str(row_id),
                    content=(
                        f"[Sender|1]\n{heading}\n{date}\n"
                        f"Итого: 0\nОператор {operator}: {amount}"
                    ),
                )

            add_report(1, "Касса SampleModel", "01.10.2026", "Анна", 50)
            add_report(2, "Касса Sampleb", "01.10.2026", "Анна", 20)
            add_report(3, "Касса SampleModel", "01.10.2026", "Анна", 50)  # correction/repost
            add_report(4, "Касса SampleModel", "02.10.2026", "Анна", 60)

            self.assertEqual(ledger.operator_statistics(), {"Анна": 13000})

            first = ledger.create_operator_payout(
                operator_name="анна",
                command_source_row_id=5,
                command_timestamp=1791000000.0,
                requester_id="810000001",
                requester_name="Owner",
            )

            self.assertEqual(first.status, "created")
            self.assertEqual(first.operator_name, "Анна")
            self.assertEqual(first.by_date, (("2026-10-01", 7000), ("2026-10-02", 6000)))
            self.assertEqual(first.total_minor, 13000)
            self.assertIn("Период: 01.10 (чт) — 02.10 (пт)", first.report)
            self.assertIn("Итого к выдаче: $130.00", first.report)

            repeated = ledger.create_operator_payout(
                operator_name="Анна",
                command_source_row_id=5,
                command_timestamp=1791000000.0,
                requester_id="810000001",
                requester_name="Owner",
            )
            self.assertEqual(repeated.status, "existing")
            self.assertEqual(repeated.report, first.report)

            add_report(6, "Касса SampleModel", "03.10.2026", "Анна", 30)
            second = ledger.create_operator_payout(
                operator_name="Анна",
                command_source_row_id=7,
                command_timestamp=1791100000.0,
                requester_id="810000001",
                requester_name="Owner",
            )

            self.assertEqual(second.by_date, (("2026-10-03", 3000),))
            self.assertEqual(second.total_minor, 3000)
            self.assertIn("Период: 03.10 (сб) — 03.10 (сб)", second.report)

    def test_statistics_use_latest_report_per_register_and_day(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            ledger = module.Ledger(Path(tmp) / "ledger.db")
            for row_id, total, operator_amount in [(1, 900, 40), (2, 1000, 50)]:
                ledger.process_message(
                    source_row_id=row_id,
                    timestamp=1790904800.0,
                    platform_message_id=str(row_id),
                    content=(
                        "[Sender|1]\nКасса SampleModel\n01.10.2026\n"
                        f"Клиент Hr/{total}\nИтого: {total}\nОператор Анна: {operator_amount}"
                    ),
                )

            stats = ledger.statistics()

            self.assertEqual(stats["days"]["2026-10-01"]["total_minor"], 100000)
            self.assertEqual(stats["days"]["2026-10-01"]["entry_count"], 1)
            self.assertEqual(stats["days"]["2026-10-01"]["checks"]["ok"], 1)
            self.assertEqual(stats["operators"], {"Анна": 5000})

    def test_parse_message_extracts_entries_sender_and_total(self):
        module = load_module()
        parsed = module.parse_message(
            "[USA❤️|810000002]\nКасса 1: 1 200\nКасса 2: 800\ntotal 2 000"
        )

        self.assertEqual(parsed.sender_id, "810000002")
        self.assertEqual(parsed.sender_name, "USA❤️")
        self.assertEqual(
            [(entry.label, entry.amount_minor) for entry in parsed.entries],
            [("Касса 1", 120000), ("Касса 2", 80000)],
        )
        self.assertEqual(parsed.claimed_total_minor, 200000)

    def test_parse_message_supports_common_cash_lines_and_ignores_time(self):
        module = load_module()
        parsed = module.parse_message(
            "[USA❤️|810000002]\nНаличные 1 200\nКарта 800\nвстреча в 14:00\ntotal 2 000"
        )

        self.assertEqual(
            [(entry.label, entry.amount_minor) for entry in parsed.entries],
            [("Наличные", 120000), ("Карта", 80000)],
        )
        self.assertEqual(parsed.claimed_total_minor, 200000)

    def test_parse_message_supports_bare_amount_lines(self):
        module = load_module()
        parsed = module.parse_message(
            "[USA❤️|810000002]\n1 200\n800\nитого 2 000"
        )

        self.assertEqual([entry.amount_minor for entry in parsed.entries], [120000, 80000])
        self.assertEqual(parsed.claimed_total_minor, 200000)

    def test_ledger_flags_incorrect_total_and_persists_entries(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            ledger = module.Ledger(Path(tmp) / "ledger.db")
            result = ledger.process_message(
                source_row_id=10,
                timestamp=1790812800.0,
                platform_message_id="42",
                content="[USA❤️|810000002]\nКасса 1: 1 200\nКасса 2: 800\ntotal 2 100",
            )

            self.assertEqual(result.status, "mismatch")
            self.assertEqual(result.computed_total_minor, 200000)
            self.assertEqual(result.claimed_total_minor, 210000)
            self.assertEqual(result.difference_minor, 10000)
            self.assertEqual(ledger.daily_total_minor("2026-10-01"), 200000)

    def test_total_only_message_checks_entries_since_previous_total(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            ledger = module.Ledger(Path(tmp) / "ledger.db")
            ledger.process_message(
                source_row_id=1,
                timestamp=1790812800.0,
                platform_message_id="1",
                content="[USA❤️|810000002]\nКасса: 1 200",
            )
            first_total = ledger.process_message(
                source_row_id=2,
                timestamp=1790812860.0,
                platform_message_id="2",
                content="[USA❤️|810000002]\ntotal: 1 200",
            )
            ledger.process_message(
                source_row_id=3,
                timestamp=1790812920.0,
                platform_message_id="3",
                content="[USA❤️|810000002]\nКасса: 500",
            )
            second_total = ledger.process_message(
                source_row_id=4,
                timestamp=1790812980.0,
                platform_message_id="4",
                content="[USA❤️|810000002]\nитого: 500",
            )

            self.assertEqual(first_total.status, "ok")
            self.assertEqual(first_total.computed_total_minor, 120000)
            self.assertEqual(second_total.status, "ok")
            self.assertEqual(second_total.computed_total_minor, 50000)

    def test_report_summarizes_period_with_details(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            ledger = module.Ledger(Path(tmp) / "ledger.db")
            ledger.process_message(
                source_row_id=1,
                timestamp=1790812800.0,
                platform_message_id="1",
                content="[USA❤️|810000002]\nКасса 1: 1 200\nКасса 2: 800\ntotal: 2 000",
            )
            ledger.process_message(
                source_row_id=2,
                timestamp=1790899200.0,
                platform_message_id="2",
                content="[USA❤️|810000002]\nКасса 1: 500\ntotal: 500",
            )

            report = ledger.report("2026-10-01", "2026-10-02", details=True)

            self.assertIn("Отчёт 01.10 (чт) — 02.10 (пт)", report)
            self.assertIn("01.10 (чт): $2,000.00", report)
            self.assertIn("Касса 1: $1,200.00", report)
            self.assertIn("02.10 (пт): $500.00", report)
            self.assertIn("Итого за период: $2,500.00", report)

    def test_monitor_reads_new_rows_once_and_writes_daily_statistics(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_db = root / "state.db"
            with closing(sqlite3.connect(source_db)) as connection:
                connection.executescript(
                    """
                    CREATE TABLE sessions (id INTEGER PRIMARY KEY, chat_id TEXT);
                    CREATE TABLE messages (
                        id INTEGER PRIMARY KEY,
                        session_id INTEGER,
                        role TEXT,
                        content TEXT,
                        timestamp REAL,
                        platform_message_id TEXT,
                        observed INTEGER,
                        active INTEGER
                    );
                    """
                )
                connection.execute(
                    "INSERT INTO sessions (id, chat_id) VALUES (1, ?)",
                    ("-1008000000001",),
                )
                connection.execute(
                    """
                    INSERT INTO messages
                    (id, session_id, role, content, timestamp, platform_message_id, observed, active)
                    VALUES (1, 1, 'user', ?, 1790812800.0, '55', 1, 1)
                    """,
                    ("[USA❤️|810000002]\nКасса Test\n01.10.2026\nКлиент Hr/1200\nКлиент Hr/800\ntotal: 2 100",),
                )
                connection.commit()
            ledger = module.Ledger(root / "ledger.db")
            state_path = root / "monitor-state.json"
            stats_path = root / "daily-stats.json"

            first = module.run_monitor(
                source_db=source_db,
                ledger=ledger,
                state_path=state_path,
                stats_path=stats_path,
                chat_id="-1008000000001",
            )
            second = module.run_monitor(
                source_db=source_db,
                ledger=ledger,
                state_path=state_path,
                stats_path=stats_path,
                chat_id="-1008000000001",
            )

            self.assertIn("Total не сходится", first)
            self.assertIn("$2,000.00", first)
            self.assertIn("$2,100.00", first)
            self.assertEqual(second, "")
            self.assertEqual(json.loads(state_path.read_text())["last_seen_message_rowid"], 1)
            stats = json.loads(stats_path.read_text())
            self.assertEqual(stats["days"]["2026-10-01"]["total_minor"], 200000)

    def test_monitor_ignores_operator_examples_without_a_register_heading(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_db = root / "state.db"
            with closing(sqlite3.connect(source_db)) as connection:
                connection.executescript(
                    """
                    CREATE TABLE sessions (id INTEGER PRIMARY KEY, chat_id TEXT);
                    CREATE TABLE messages (
                        id INTEGER PRIMARY KEY, session_id INTEGER, role TEXT,
                        content TEXT, timestamp REAL, platform_message_id TEXT,
                        observed INTEGER, active INTEGER
                    );
                    """
                )
                connection.execute("INSERT INTO sessions (id, chat_id) VALUES (1, '-1008000000001')")
                connection.execute(
                    """
                    INSERT INTO messages VALUES
                    (1, 1, 'user', ?, 1790812800.0, '1', 0, 1)
                    """,
                    ("[Owner|810000001]\nпример: Tester Operator +40\nОператор Анна: 20",),
                )
                connection.commit()

            ledger = module.Ledger(root / "ledger.db")
            state_path = root / "monitor-state.json"
            stats_path = root / "daily-stats.json"
            output = module.run_monitor(
                source_db=source_db,
                ledger=ledger,
                state_path=state_path,
                stats_path=stats_path,
                chat_id="-1008000000001",
            )

            self.assertEqual(output, "")
            self.assertEqual(ledger.operator_statistics(), {})
            self.assertEqual(ledger.daily_total_minor("2026-10-01"), 0)
            self.assertEqual(json.loads(state_path.read_text())["last_seen_message_rowid"], 1)

    def test_monitor_executes_exact_operator_payout_command_once(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_db = root / "state.db"
            with closing(sqlite3.connect(source_db)) as connection:
                connection.executescript(
                    """
                    CREATE TABLE sessions (id INTEGER PRIMARY KEY, chat_id TEXT);
                    CREATE TABLE messages (
                        id INTEGER PRIMARY KEY, session_id INTEGER, role TEXT,
                        content TEXT, timestamp REAL, platform_message_id TEXT,
                        observed INTEGER, active INTEGER
                    );
                    """
                )
                connection.execute("INSERT INTO sessions (id, chat_id) VALUES (1, '-1008000000001')")
                connection.executemany(
                    "INSERT INTO messages VALUES (?, 1, 'user', ?, ?, ?, 1, 1)",
                    [
                        (
                            1,
                            "[Sender|1]\nКасса Sampleb\n01.10.2026\nИтого: 0\nОператор Анна: 20",
                            1790904800.0,
                            "1",
                        ),
                        (2, "[Owner|810000001]\nВыдача анна", 1791000000.0, "2"),
                    ],
                )
                connection.commit()

            ledger = module.Ledger(root / "ledger.db")
            state_path = root / "monitor-state.json"
            stats_path = root / "daily-stats.json"
            first = module.run_monitor(
                source_db=source_db,
                ledger=ledger,
                state_path=state_path,
                stats_path=stats_path,
                chat_id="-1008000000001",
            )
            second = module.run_monitor(
                source_db=source_db,
                ledger=ledger,
                state_path=state_path,
                stats_path=stats_path,
                chat_id="-1008000000001",
            )

            self.assertIn("Выдача Анна", first)
            self.assertIn("Период: 01.10 (чт) — 01.10 (чт)", first)
            self.assertIn("Итого к выдаче: $20.00", first)
            self.assertEqual(second, "")
            with closing(sqlite3.connect(root / "ledger.db")) as connection:
                payout_count = connection.execute("SELECT COUNT(*) FROM operator_payouts").fetchone()[0]
            self.assertEqual(payout_count, 1)

    def test_monitor_executes_model_payout_command_once(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_db = root / "state.db"
            with closing(sqlite3.connect(source_db)) as connection:
                connection.executescript(
                    """
                    CREATE TABLE sessions (id INTEGER PRIMARY KEY, chat_id TEXT);
                    CREATE TABLE messages (
                        id INTEGER PRIMARY KEY, session_id INTEGER, role TEXT,
                        content TEXT, timestamp REAL, platform_message_id TEXT,
                        observed INTEGER, active INTEGER
                    );
                    """
                )
                connection.execute("INSERT INTO sessions (id, chat_id) VALUES (1, '-1008000000001')")
                connection.executemany(
                    "INSERT INTO messages VALUES (?, 1, 'user', ?, ?, ?, 1, 1)",
                    [
                        (
                            1,
                            "[Sender|1]\nКасса SampleModel\n01.10.2026\nИтого: 0\nМодели: 840",
                            1790904800.0,
                            "1",
                        ),
                        (2, "[Owner|810000001]\nВыдача SampleModel", 1791000000.0, "2"),
                    ],
                )
                connection.commit()

            ledger = module.Ledger(root / "ledger.db")
            state_path = root / "monitor-state.json"
            stats_path = root / "daily-stats.json"
            first = module.run_monitor(
                source_db=source_db,
                ledger=ledger,
                state_path=state_path,
                stats_path=stats_path,
                chat_id="-1008000000001",
            )
            second = module.run_monitor(
                source_db=source_db,
                ledger=ledger,
                state_path=state_path,
                stats_path=stats_path,
                chat_id="-1008000000001",
            )

            self.assertIn("Выдача SampleModel", first)
            self.assertIn("Период: 01.10 (чт) — 01.10 (чт)", first)
            self.assertIn("Итого к выдаче: $840.00", first)
            self.assertIn("SampleModel: 840$ — с 01.10 (чт) (выплат ещё не было)", first)
            self.assertNotIn("✅ Total сходится: $0.00", first)
            self.assertEqual(second, "")
            with closing(sqlite3.connect(root / "ledger.db")) as connection:
                payout_count = connection.execute("SELECT COUNT(*) FROM model_payouts").fetchone()[0]
            self.assertEqual(payout_count, 1)

    def test_monitor_refuses_standalone_agency_payout(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_db = root / "state.db"
            with closing(sqlite3.connect(source_db)) as connection:
                connection.executescript(
                    """
                    CREATE TABLE sessions (id INTEGER PRIMARY KEY, chat_id TEXT);
                    CREATE TABLE messages (
                        id INTEGER PRIMARY KEY, session_id INTEGER, role TEXT,
                        content TEXT, timestamp REAL, platform_message_id TEXT,
                        observed INTEGER, active INTEGER
                    );
                    """
                )
                connection.execute("INSERT INTO sessions (id, chat_id) VALUES (1, '-1008000000001')")
                connection.executemany(
                    "INSERT INTO messages VALUES (?, 1, 'user', ?, ?, ?, 1, 1)",
                    [
                        (
                            1,
                            "[Sender|1]\nКасса SampleModel\n01.10.2026\nИтого: 0\nАгентских: 560",
                            1790904800.0,
                            "1",
                        ),
                        (2, "[Owner|810000001]\nВыдача агентству SampleModel", 1791000000.0, "2"),
                    ],
                )
                connection.commit()

            ledger = module.Ledger(root / "ledger.db")
            state_path = root / "monitor-state.json"
            stats_path = root / "daily-stats.json"
            first = module.run_monitor(
                source_db=source_db,
                ledger=ledger,
                state_path=state_path,
                stats_path=stats_path,
                chat_id="-1008000000001",
            )
            second = module.run_monitor(
                source_db=source_db,
                ledger=ledger,
                state_path=state_path,
                stats_path=stats_path,
                chat_id="-1008000000001",
            )

            self.assertIn("Выплата агентства совпадает с выплатой модели", first)
            self.assertIn("Агентство: 560$ — с 01.10 (чт) (выплат ещё не было)", first)
            self.assertNotIn("✅ Total сходится: $0.00", first)
            self.assertEqual(second, "")
            with closing(sqlite3.connect(root / "ledger.db")) as connection:
                payout_count = connection.execute("SELECT COUNT(*) FROM agency_payouts").fetchone()[0]
            self.assertEqual(payout_count, 0)

    def test_report_cli_prints_requested_period(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            ledger_path = Path(tmp) / "ledger.db"
            ledger = module.Ledger(ledger_path)
            ledger.process_message(
                source_row_id=1,
                timestamp=1790812800.0,
                platform_message_id="1",
                content="[USA❤️|810000002]\nКасса: 750\ntotal: 750",
            )
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = module.main(
                    [
                        "--ledger",
                        str(ledger_path),
                        "report",
                        "--from-date",
                        "2026-10-01",
                        "--to-date",
                        "2026-10-01",
                        "--details",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertIn("Итого за период: $750.00", output.getvalue())


if __name__ == "__main__":
    unittest.main()
