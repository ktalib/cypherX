"""
Household money apps: Bills and Groceries. Stored in the app's SQLite database.

Bills
  recurring household bills (rent, electricity, internet, DSTV, water...) with a
  frequency and a due day. "Paid" is per period: marking a monthly bill paid in
  October leaves it unpaid again in November. Every bill is normalised to a
  monthly amount so the monthly total and the per-person split are honest.

Groceries
  named shopping lists of items (quantity x unit price) with a budget, a bought
  tick per item, and a price memory: the last price used for an item name is
  offered the next time that item is added.
"""
import calendar
from datetime import date, datetime

FREQUENCIES = ("Monthly", "Weekly", "Quarterly", "Yearly", "One-off")
MONTHLY_FACTOR = {"Monthly": 1.0, "Weekly": 52 / 12, "Quarterly": 1 / 3, "Yearly": 1 / 12, "One-off": 0.0}
BILL_CATEGORIES = ("Housing", "Utilities", "Electricity", "Internet & TV", "Transport", "School",
                   "Insurance", "Subscriptions", "Other")
GROCERY_CATEGORIES = ("Food", "Drinks", "Toiletries", "Cleaning", "Baby", "Household", "Other")


def period_key(freq, day=None):
    """Identifier of the current billing period for a frequency."""
    d = day or date.today()
    if freq == "Weekly":
        y, w, _ = d.isocalendar()
        return f"{y}-W{w:02d}"
    if freq == "Quarterly":
        return f"{d.year}-Q{(d.month - 1) // 3 + 1}"
    if freq == "Yearly":
        return str(d.year)
    if freq == "One-off":
        return "once"
    return f"{d.year}-{d.month:02d}"


def next_due(freq, due_day, today=None):
    """Next due date for a bill (None for weekly / one-off without a date)."""
    t = today or date.today()
    if freq in ("Weekly", "One-off") or not due_day:
        return None
    due_day = int(due_day)

    def clamp(y, m):
        return date(y, m, min(due_day, calendar.monthrange(y, m)[1]))

    if freq == "Monthly":
        d = clamp(t.year, t.month)
        if d < t:
            y, m = (t.year + 1, 1) if t.month == 12 else (t.year, t.month + 1)
            d = clamp(y, m)
        return d
    if freq == "Quarterly":
        m = ((t.month - 1) // 3) * 3 + 3          # last month of this quarter
        d = clamp(t.year, m)
        if d < t:
            y, m = (t.year + 1, 3) if m == 12 else (t.year, m + 3)
            d = clamp(y, m)
        return d
    # Yearly: due in December of each year on due_day (simple, predictable)
    d = clamp(t.year, 12)
    return d if d >= t else clamp(t.year + 1, 12)


def _passed_this_period(freq, due_day, today=None):
    """True when this period's due date has already gone by."""
    t = today or date.today()
    if not due_day or freq in ("Weekly", "One-off"):
        return False
    if freq == "Monthly":
        m = t.month
    elif freq == "Quarterly":
        m = ((t.month - 1) // 3) * 3 + 3
    else:
        m = 12
    return date(t.year, m, min(int(due_day), calendar.monthrange(t.year, m)[1])) < t



# Called as hook(name, qty) when a grocery item is ticked bought (qty < 0 when un-ticked).
# The fridge stock uses it so buying eggs adds them to the fridge.
BOUGHT_HOOKS = []

class BudgetService:
    def __init__(self, db):
        self.db = db
        with db._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS bills (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    amount REAL NOT NULL,
                    frequency TEXT NOT NULL DEFAULT 'Monthly',
                    due_day INTEGER,
                    category TEXT DEFAULT 'Other',
                    paid_period TEXT,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS grocery_lists (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    budget REAL DEFAULT 0,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS grocery_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    list_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    qty REAL NOT NULL DEFAULT 1,
                    unit_price REAL NOT NULL DEFAULT 0,
                    category TEXT DEFAULT 'Food',
                    bought INTEGER DEFAULT 0,
                    position INTEGER DEFAULT 0
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS grocery_prices (
                    name TEXT PRIMARY KEY COLLATE NOCASE,
                    unit_price REAL NOT NULL,
                    category TEXT,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.commit()

    def _q(self, sql, args=(), commit=False):
        with self.db._get_connection() as conn:
            cur = conn.execute(sql, args)
            if commit:
                conn.commit()
                return cur.lastrowid
            return [dict(r) for r in cur.fetchall()]

    # -------------------------------------------------------------- bills --

    def bills(self, today=None):
        rows = self._q("SELECT * FROM bills ORDER BY due_day IS NULL, due_day, name")
        for b in rows:
            b["paid"] = b["paid_period"] == period_key(b["frequency"], today)
            b["monthly"] = b["amount"] * MONTHLY_FACTOR.get(b["frequency"], 1.0)
            b["next_due"] = next_due(b["frequency"], b["due_day"], today)
            b["overdue"] = not b["paid"] and _passed_this_period(b["frequency"], b["due_day"], today)
        return rows

    def add_bill(self, name, amount, frequency="Monthly", due_day=None, category="Other"):
        if frequency not in FREQUENCIES:
            raise ValueError("Unknown frequency")
        return self._q("INSERT INTO bills (name, amount, frequency, due_day, category, created_at) "
                       "VALUES (?, ?, ?, ?, ?, ?)",
                       (name.strip(), float(amount), frequency, int(due_day) if due_day else None,
                        category, _now()), commit=True)

    def update_bill(self, bill_id, **fields):
        allowed = {"name", "amount", "frequency", "due_day", "category"}
        sets = {k: v for k, v in fields.items() if k in allowed}
        if sets:
            cols = ", ".join(f"{k} = ?" for k in sets)
            self._q(f"UPDATE bills SET {cols} WHERE id = ?", (*sets.values(), bill_id), commit=True)

    def set_paid(self, bill_id, paid, today=None):
        b = self._q("SELECT frequency FROM bills WHERE id = ?", (bill_id,))
        if b:
            self._q("UPDATE bills SET paid_period = ? WHERE id = ?",
                    (period_key(b[0]["frequency"], today) if paid else None, bill_id), commit=True)

    def remove_bill(self, bill_id):
        self._q("DELETE FROM bills WHERE id = ?", (bill_id,), commit=True)

    def bill_summary(self, people=1, today=None):
        bills = self.bills(today)
        monthly = sum(b["monthly"] for b in bills)
        recurring = [b for b in bills if b["frequency"] != "One-off"]
        unpaid = [b for b in bills if not b["paid"]]
        t = today or date.today()
        upcoming = sorted((b for b in unpaid if b["next_due"]), key=lambda b: b["next_due"])
        overdue_soon = [b for b in upcoming if (b["next_due"] - t).days <= 3]
        return {
            "monthly": monthly,
            "per_person": monthly / max(1, int(people)),
            "count": len(recurring),
            "paid_count": sum(1 for b in bills if b["paid"]),
            "unpaid_total": sum(b["amount"] for b in unpaid),
            "overdue": [b for b in bills if b["overdue"]],
            "due_this_month": sum(b["amount"] for b in unpaid if b["overdue"] or
                                  (b["next_due"] and (b["next_due"].year, b["next_due"].month) == (t.year, t.month))),
            "next": upcoming[0] if upcoming else None,
            "due_soon": overdue_soon,
            "by_category": _group_sum(bills, "category", "monthly"),
        }

    # ---------------------------------------------------------- groceries --

    def lists(self):
        return self._q("SELECT * FROM grocery_lists ORDER BY id DESC")

    def add_list(self, name, budget=0.0, copy_from=None):
        list_id = self._q("INSERT INTO grocery_lists (name, budget, created_at) VALUES (?, ?, ?)",
                          (name.strip(), float(budget), _now()), commit=True)
        if copy_from:
            for it in self.items(copy_from):
                self.add_item(list_id, it["name"], it["qty"], it["unit_price"], it["category"],
                              remember=False)
        return list_id

    def update_list(self, list_id, **fields):
        sets = {k: v for k, v in fields.items() if k in ("name", "budget")}
        if sets:
            cols = ", ".join(f"{k} = ?" for k in sets)
            self._q(f"UPDATE grocery_lists SET {cols} WHERE id = ?", (*sets.values(), list_id), commit=True)

    def remove_list(self, list_id):
        self._q("DELETE FROM grocery_items WHERE list_id = ?", (list_id,), commit=True)
        self._q("DELETE FROM grocery_lists WHERE id = ?", (list_id,), commit=True)

    def items(self, list_id):
        rows = self._q("SELECT * FROM grocery_items WHERE list_id = ? ORDER BY bought, position, id",
                       (list_id,))
        for r in rows:
            r["total"] = r["qty"] * r["unit_price"]
        return rows

    def add_item(self, list_id, name, qty=1, unit_price=None, category=None, remember=True):
        name = name.strip()
        known = self.remembered_price(name)
        if unit_price is None:
            unit_price = known["unit_price"] if known else 0.0
        if category is None:
            category = (known or {}).get("category") or "Food"
        pos = self._q("SELECT COALESCE(MAX(position), 0) + 1 AS p FROM grocery_items WHERE list_id = ?",
                      (list_id,))[0]["p"]
        item_id = self._q("INSERT INTO grocery_items (list_id, name, qty, unit_price, category, position) "
                          "VALUES (?, ?, ?, ?, ?, ?)",
                          (list_id, name, float(qty), float(unit_price), category, pos), commit=True)
        if remember and unit_price:
            self.remember_price(name, unit_price, category)
        return item_id

    def update_item(self, item_id, **fields):
        sets = {k: v for k, v in fields.items() if k in ("name", "qty", "unit_price", "category", "bought")}
        if not sets:
            return
        before = self._q("SELECT name, qty, bought FROM grocery_items WHERE id = ?", (item_id,)) \
            if "bought" in sets else None
        cols = ", ".join(f"{k} = ?" for k in sets)
        self._q(f"UPDATE grocery_items SET {cols} WHERE id = ?", (*sets.values(), item_id), commit=True)
        if "unit_price" in sets or "name" in sets:
            it = self._q("SELECT name, unit_price, category FROM grocery_items WHERE id = ?", (item_id,))
            if it and it[0]["unit_price"]:
                self.remember_price(it[0]["name"], it[0]["unit_price"], it[0]["category"])
        if before and bool(before[0]["bought"]) != bool(sets["bought"]):
            sign = 1 if sets["bought"] else -1
            for hook in list(BOUGHT_HOOKS):
                try:
                    hook(before[0]["name"], sign * float(before[0]["qty"] or 1))
                except Exception:
                    pass

    def remove_item(self, item_id):
        self._q("DELETE FROM grocery_items WHERE id = ?", (item_id,), commit=True)

    def clear_bought(self, list_id):
        self._q("DELETE FROM grocery_items WHERE list_id = ? AND bought = 1", (list_id,), commit=True)

    def remember_price(self, name, unit_price, category=None):
        self._q("INSERT INTO grocery_prices (name, unit_price, category, updated_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(name) DO UPDATE SET unit_price = excluded.unit_price, "
                "category = COALESCE(excluded.category, grocery_prices.category), updated_at = excluded.updated_at",
                (name.strip(), float(unit_price), category, _now()), commit=True)

    def remembered_price(self, name):
        r = self._q("SELECT * FROM grocery_prices WHERE name = ?", (name.strip(),))
        return r[0] if r else None

    def known_items(self):
        return [r["name"] for r in self._q("SELECT name FROM grocery_prices ORDER BY name")]

    def list_summary(self, list_id):
        items = self.items(list_id)
        lst = self._q("SELECT * FROM grocery_lists WHERE id = ?", (list_id,))
        budget = lst[0]["budget"] if lst else 0.0
        total = sum(i["total"] for i in items)
        bought = sum(i["total"] for i in items if i["bought"])
        return {
            "total": total,
            "bought": bought,
            "remaining": total - bought,
            "budget": budget,
            "left_in_budget": budget - total if budget else None,
            "count": len(items),
            "bought_count": sum(1 for i in items if i["bought"]),
            "by_category": _group_sum(items, "category", "total"),
        }


def get_currency(db):
    """Currency symbol for the money apps (Settings key "currency", default ₦)."""
    try:
        return db.get_setting("currency", None) or "₦"
    except Exception:
        return "₦"


def _group_sum(rows, key, field):
    out = {}
    for r in rows:
        out[r.get(key) or "Other"] = out.get(r.get(key) or "Other", 0.0) + r[field]
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
