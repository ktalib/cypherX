import os
import shutil
import tempfile
import unittest
from datetime import date
from pathlib import Path
from app.database import Database
from app.services.auth_service import AuthService, AuthError, hash_password, verify_password
from app.services.budget_service import BudgetService, next_due, period_key


class _TempDb(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="cyberops_test_db_")
        self.db = Database(Path(self.dir) / "t.db")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)


class TestAuth(_TempDb):
    def test_hashing(self):
        h = hash_password("secret")
        self.assertNotIn("secret", h)
        self.assertTrue(verify_password("secret", h))
        self.assertFalse(verify_password("Secret", h))
        self.assertFalse(verify_password("x", "garbage"))

    def test_default_admin_is_root(self):
        auth = AuthService(self.db)
        user = auth.authenticate("admin", "admin")
        self.assertEqual(user["role"], "root")
        self.assertTrue(auth.uses_default_password())
        self.assertIsNone(auth.authenticate("admin", "wrong"))
        self.assertIsNone(auth.authenticate("nobody", "admin"))
        # a second start does not re-create or reset admin
        auth.change_password("admin", "admin", "n3w-pass")
        auth2 = AuthService(self.db)
        self.assertIsNone(auth2.authenticate("admin", "admin"))
        self.assertIsNotNone(auth2.authenticate("ADMIN", "n3w-pass"))   # names are case-insensitive
        self.assertFalse(auth2.uses_default_password())

    def test_users_and_last_root(self):
        auth = AuthService(self.db)
        auth.add_user("mum", "1234")
        self.assertEqual(auth.authenticate("mum", "1234")["role"], "user")
        with self.assertRaises(AuthError):
            auth.add_user("mum", "abcd")
        with self.assertRaises(AuthError):
            auth.add_user("x y", "abcd")
        with self.assertRaises(AuthError):
            auth.change_password("mum", "wrong", "abcd")
        with self.assertRaises(AuthError):
            auth.remove_user("admin")          # last root
        auth.reset_password("mum", "5678")
        self.assertIsNotNone(auth.authenticate("mum", "5678"))
        auth.remove_user("mum")
        self.assertEqual([u["username"] for u in auth.users()], ["admin"])


class TestBills(_TempDb):
    def test_period_and_due_dates(self):
        d = date(2026, 10, 18)
        self.assertEqual(period_key("Monthly", d), "2026-10")
        self.assertEqual(period_key("Quarterly", d), "2026-Q4")
        self.assertEqual(next_due("Monthly", 25, d), date(2026, 10, 25))
        self.assertEqual(next_due("Monthly", 5, d), date(2026, 11, 5))
        self.assertEqual(next_due("Monthly", 31, date(2027, 2, 10)), date(2027, 2, 28))
        self.assertEqual(next_due("Monthly", 5, date(2026, 12, 20)), date(2027, 1, 5))
        self.assertIsNone(next_due("Weekly", 3, d))

    def test_summary_and_paid_per_period(self):
        b = BudgetService(self.db)
        oct18, nov2 = date(2026, 10, 18), date(2026, 11, 2)
        rent = b.add_bill("Rent", 120000, "Yearly", 1, "Housing")
        net = b.add_bill("Internet", 15000, "Monthly", 20, "Internet & TV")
        b.add_bill("Gas refill", 6000, "One-off")
        s = b.bill_summary(people=2, today=oct18)
        self.assertAlmostEqual(s["monthly"], 10000 + 15000)
        self.assertAlmostEqual(s["per_person"], 12500)
        self.assertEqual(s["next"]["name"], "Internet")          # due 20 Oct
        self.assertEqual([x["name"] for x in s["due_soon"]], ["Internet"])
        self.assertAlmostEqual(s["due_this_month"], 15000)      # rent is due in December
        b.set_paid(net, True, today=oct18)
        self.assertTrue(next(x for x in b.bills(oct18) if x["id"] == net)["paid"])
        self.assertFalse(next(x for x in b.bills(nov2) if x["id"] == net)["paid"])   # new month
        late = b.add_bill("Water", 3000, "Monthly", 10, "Utilities")
        self.assertEqual([x["name"] for x in b.bill_summary(today=oct18)["overdue"]], ["Water"])
        b.set_paid(late, True, today=oct18)
        self.assertEqual(b.bill_summary(today=oct18)["overdue"], [])
        b.remove_bill(late)
        b.update_bill(rent, amount=240000)
        self.assertAlmostEqual(b.bill_summary(today=oct18)["monthly"], 20000 + 15000)


class TestGroceries(_TempDb):
    def test_list_totals_budget_and_price_memory(self):
        b = BudgetService(self.db)
        lst = b.add_list("Weekly shop", budget=20000)
        b.add_item(lst, "Rice 5kg", 1, 9500)
        eggs = b.add_item(lst, "Eggs (crate)", 2, 4200)
        b.update_item(eggs, bought=1)
        s = b.list_summary(lst)
        self.assertAlmostEqual(s["total"], 17900)
        self.assertAlmostEqual(s["bought"], 8400)
        self.assertAlmostEqual(s["left_in_budget"], 2100)
        # price memory fills in the price next time
        lst2 = b.add_list("Next week", copy_from=lst)
        self.assertEqual(len(b.items(lst2)), 2)
        new = b.add_item(lst2, "rice 5KG")
        self.assertAlmostEqual(next(i for i in b.items(lst2) if i["id"] == new)["unit_price"], 9500)
        b.clear_bought(lst)
        self.assertEqual([i["name"] for i in b.items(lst)], ["Rice 5kg"])
        b.remove_list(lst)
        self.assertEqual([l["id"] for l in b.lists()], [lst2])


if __name__ == "__main__":
    unittest.main()
