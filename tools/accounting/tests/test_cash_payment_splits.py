import unittest
from test_cash_ledger_monitor import load_module

REPORT='''PROFIT REGISTER Fixture
Fixture City
12.02.2026
1️⃣ ✅Client 9:05 am qv/170
Cash
2️⃣ ✅Client 11:05 am Hr/310
Депозит Zelle (Fixture Holder) 230 +80 Cash
Zelle+Cash
3️⃣ ✅Client 1:05 pm Hhr/230
Cash
4️⃣ ✅Client 3:05 pm Hhr/230
Cash
5️⃣ ✅Client 5:05 pm Hhr/230
Депозит Zelle (Fixture Holder) 80 +150 Cash
Zelle+Cash
Total: 1170
Of which:
(230+80)Zelle (Fixture Holder)
(860) Cash
Yours: 710
Agent fees: 460
Anna operator: 19'''

class PaymentSplitTests(unittest.TestCase):
    def test_named_parenthesized_payment_terms_match_existing_tariff(self):
        report='''Касса FixtureSplit
10 .02
Client 10:00 Hr/170
Cash
Client 13:30 Hr/170
Cash
Client 15:00 Hr/170
Cash
Client 16:30 Hr/170
Cash
Client 20:00 3Hrs/610 outcall
Zelle (110 депозит) + Venmo (390) + Zelle (110)
Итого: 1290
Из них:
(390) Venmo
(110+110) Zelle
(680) Cash
Модели: 770
Агентских: 520
Оператор Тестовая: 23'''
        p=load_module().parse_message(report)
        self.assertEqual(p.review_lines,())
        self.assertEqual([e.amount_minor for e in p.entries],[17000]*4+[61000])
        self.assertEqual(sum(e.amount_minor for e in p.entries),129000)
        self.assertEqual(p.claimed_total_minor,129000)
        self.assertEqual(p.model_amount_minor,77000)
        self.assertEqual(p.agency_amount_minor,52000)
        self.assertEqual([(o.name,o.amount_minor) for o in p.operators],[('Тестовая',2300)])

    def test_numeric_hour_duration_price_is_one_transaction(self):
        for duration in ('3Hrs','2Hr','3 hours','3 hrs'):
            with self.subTest(duration=duration):
                p=load_module().parse_message('Касса FixtureSplit\nClient 20:00 '+duration+'/610 outcall\nTotal: 610')
                self.assertEqual([e.amount_minor for e in p.entries],[61000])
                self.assertEqual(p.review_lines,())

    def test_mismatching_parenthesized_components_remain_unverified(self):
        line='Zelle (110 депозит) + Venmo (390) + Zelle (111)'
        p=load_module().parse_message('Касса FixtureSplit\nClient 3Hrs/610\n'+line+'\nИтого: 610')
        self.assertEqual([e.amount_minor for e in p.entries],[61000])
        self.assertEqual(p.review_lines,(line,))

    def test_parenthesized_payments_after_total_do_not_add_revenue(self):
        p=load_module().parse_message('Касса FixtureSplit\nClient 3Hrs/610\nИтого: 610\nZelle (110 депозит) + Venmo (390) + Zelle (110)')
        self.assertEqual(sum(e.amount_minor for e in p.entries),61000)
        self.assertEqual(p.review_lines,())

    def test_mismatching_payment_split_requires_review(self):
        p=load_module().parse_message('Касса Fixture\nClient Hr/400\nДепозит Zelle 100 +200 Cash\nTotal: 400')
        self.assertEqual([e.amount_minor for e in p.entries],[40000])
        self.assertEqual(p.review_lines,('Депозит Zelle 100 +200 Cash',))

    def test_standalone_payment_addition_counts_once_above_total(self):
        p=load_module().parse_message('Касса Fixture\n100+300\nTotal: 400\nOf which: 100+300\nYours: 240\nAgent fees: 160')
        self.assertEqual([e.amount_minor for e in p.entries],[40000])
        self.assertFalse(p.review_lines)

    def test_split_payments_verify_tariff_without_double_counting(self):
        p=load_module().parse_message(REPORT)
        self.assertEqual([e.amount_minor for e in p.entries],[17000,31000,23000,23000,23000])
        self.assertEqual(sum(e.amount_minor for e in p.entries),117000)
        self.assertEqual(p.review_lines,())
        self.assertEqual(p.model_amount_minor,71000)
        self.assertEqual(p.agency_amount_minor,46000)
