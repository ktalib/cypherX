"""
Bills — household bills with due dates, paid-this-month ticks and a split
between the people in the house.
"""
from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton, QFrame, QScrollArea,
    QSpinBox, QDialog, QFormLayout, QLineEdit, QDoubleSpinBox, QComboBox, QDialogButtonBox,
    QMessageBox
)

from app.database import Database
from app.services.budget_service import BudgetService, FREQUENCIES, BILL_CATEGORIES, get_currency
from app.views.smart_dashboard import StatTile, RoomBars, _card, _action, _lbl, _chip_style
from app.views.smart_dashboard import ACCENT, GOOD, WARN, CRIT, TEXT, SOFT, MUTED, DIM
from app.widgets.home.common import make_menu, hicon


def _money(cur, v):
    return f"{cur}{v:,.0f}"


def _due_text(b, today):
    if b["paid"]:
        return "Paid this period", GOOD
    if b["overdue"]:
        return "Overdue", CRIT
    d = b["next_due"]
    if d is None:
        return b["frequency"], MUTED
    days = (d - today).days
    when = "today" if days == 0 else "tomorrow" if days == 1 else f"in {days} days"
    return f"Due {d:%d %b} · {when}", WARN if days <= 3 else MUTED


class BillDialog(QDialog):
    def __init__(self, cur, bill=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit bill" if bill else "Add bill")
        form = QFormLayout(self)
        self.name = QLineEdit(bill["name"] if bill else "")
        self.name.setPlaceholderText("e.g. Rent, Internet, DSTV, Water")
        self.amount = QDoubleSpinBox()
        self.amount.setRange(0, 1_000_000_000)
        self.amount.setDecimals(0)
        self.amount.setSingleStep(1000)
        self.amount.setPrefix(cur + " ")
        self.amount.setGroupSeparatorShown(True)
        self.amount.setValue(bill["amount"] if bill else 0)
        self.freq = QComboBox()
        self.freq.addItems(FREQUENCIES)
        self.freq.setCurrentText(bill["frequency"] if bill else "Monthly")
        self.due = QSpinBox()
        self.due.setRange(0, 31)
        self.due.setSpecialValueText("—  (no fixed day)")
        self.due.setValue(bill["due_day"] or 0 if bill else 0)
        self.cat = QComboBox()
        self.cat.addItems(BILL_CATEGORIES)
        self.cat.setCurrentText(bill["category"] if bill else "Other")
        form.addRow("Name", self.name)
        form.addRow("Amount", self.amount)
        form.addRow("How often", self.freq)
        form.addRow("Due day of month", self.due)
        form.addRow("Category", self.cat)
        note = QLabel("Yearly bills fall due in December on that day; quarterly ones in the last "
                      "month of each quarter.")
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{DIM};font-size:11px;")
        form.addRow(note)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

    def _ok(self):
        if not self.name.text().strip():
            self.name.setFocus()
            return
        self.accept()

    def values(self):
        return dict(name=self.name.text().strip(), amount=self.amount.value(),
                    frequency=self.freq.currentText(), due_day=self.due.value() or None,
                    category=self.cat.currentText())


class BillRow(QFrame):
    def __init__(self, view, bill, cur, today, parent=None):
        super().__init__(parent)
        self.setObjectName(f"bill_{bill['id']}")
        self.setAttribute(Qt.WA_StyledBackground, True)
        due, color = _due_text(bill, today)
        border = "rgba(244,63,94,0.55)" if bill["overdue"] else "rgba(255,255,255,0.10)"
        self.setStyleSheet(f"QFrame#{self.objectName()}{{background:rgba(255,255,255,0.04);"
                           f"border:1px solid {border};border-radius:12px;}}")
        lo = QHBoxLayout(self)
        lo.setContentsMargins(10, 8, 8, 8)
        lo.setSpacing(10)
        paid = QPushButton("PAID" if bill["paid"] else "MARK PAID")
        paid.setCursor(Qt.PointingHandCursor)
        paid.setFixedSize(86, 24)
        paid.setToolTip("Mark as unpaid" if bill["paid"] else "Mark as paid for this period")
        paid.setStyleSheet(
            f"QPushButton{{background:{GOOD};color:#04140d;border:none;border-radius:11px;padding:4px;"
            "font-size:10px;font-weight:800;}" if bill["paid"] else
            "QPushButton{background:rgba(255,255,255,0.07);color:#cbd5e1;border:1px solid "
            "rgba(255,255,255,0.16);border-radius:11px;padding:4px;font-size:10px;font-weight:800;}"
            "QPushButton:hover{background:rgba(16,185,129,0.25);}")
        paid.clicked.connect(lambda: view.toggle_paid(bill))
        lo.addWidget(paid)
        col = QVBoxLayout()
        col.setSpacing(1)
        col.addWidget(_lbl(bill["name"], TEXT if not bill["paid"] else SOFT, 13, 700))
        col.addWidget(_lbl(f"{bill['category']}  ·  {bill['frequency']}", MUTED, 10, 500))
        lo.addLayout(col, 1)
        right = QVBoxLayout()
        right.setSpacing(1)
        amt = _lbl(_money(cur, bill["amount"]), TEXT, 14, 700)
        amt.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        due_lbl = _lbl(due, color, 10, 700)
        due_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        right.addWidget(amt)
        right.addWidget(due_lbl)
        lo.addLayout(right)
        more = QPushButton()
        more.setFixedSize(28, 26)
        more.setIcon(hicon("more", "#cbd5e1", 14))
        more.setCursor(Qt.PointingHandCursor)
        more.clicked.connect(lambda: view.bill_menu(bill))
        lo.addWidget(more)


class BillsView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.db = Database.get_instance()
        self.svc = BudgetService(self.db)
        self._build()
        self.refresh()

    def _build(self):
        main = QVBoxLayout(self)
        main.setContentsMargins(14, 14, 14, 14)
        main.setSpacing(12)

        bar = QFrame()
        bar.setObjectName("panel")
        tb = QHBoxLayout(bar)
        tb.setContentsMargins(14, 8, 10, 8)
        t = QLabel("BILLS // HOUSEHOLD")
        t.setObjectName("section-header")
        tb.addWidget(t)
        tb.addStretch()
        tb.addWidget(_lbl("Split between", MUTED, 11, 600))
        self.people = QSpinBox()
        self.people.setRange(1, 20)
        self.people.setSuffix(" people")
        self.people.setValue(int(self.db.get_setting("bills_people", 1) or 1))
        self.people.valueChanged.connect(self._people_changed)
        tb.addWidget(self.people)
        tb.addSpacing(8)
        tb.addWidget(_action("Add bill", "plus", self._add, primary=True))
        main.addWidget(bar)

        tiles = QGridLayout()
        tiles.setHorizontalSpacing(12)
        self.t_month = StatTile("Every month", "calendar", ring=False)
        self.t_split = StatTile("Per person", "user", ring=False)
        self.t_paid = StatTile("Paid this period", "check_square")
        self.t_next = StatTile("Next due", "bell", ring=False)
        for i, w in enumerate((self.t_month, self.t_split, self.t_paid, self.t_next)):
            tiles.addWidget(w, 0, i)
            tiles.setColumnStretch(i, 1)
        main.addLayout(tiles)

        body = QHBoxLayout()
        body.setSpacing(12)
        card, lo, head = _card("Your bills", "file_text")
        self.count_lbl = _lbl("", MUTED, 11, 600)
        head.addWidget(self.count_lbl)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea{background:transparent;}")
        holder = QWidget()
        holder.setStyleSheet("background:transparent;")
        self.rows = QVBoxLayout(holder)
        self.rows.setContentsMargins(0, 0, 4, 0)
        self.rows.setSpacing(6)
        scroll.setWidget(holder)
        lo.addWidget(scroll, 1)
        body.addWidget(card, 3)

        card, lo, _ = _card("Monthly cost by category", "pie_chart")
        self.cats = RoomBars(fmt=lambda v: _money(get_currency(self.db), v), share_of="the monthly total",
                             click_hint=None, name_w=110, val_w=90)
        lo.addWidget(self.cats)
        self.cat_note = _lbl("", MUTED, 10, 500)
        self.cat_note.setWordWrap(True)
        lo.addWidget(self.cat_note)
        lo.addStretch()
        body.addWidget(card, 2)
        main.addLayout(body, 1)

    # --------------------------------------------------------------- refresh --

    def showEvent(self, e):
        super().showEvent(e)
        self.refresh()          # a new month may have started since the last look

    def refresh(self):
        cur = get_currency(self.db)
        today = date.today()
        people = self.people.value()
        s = self.svc.bill_summary(people=people, today=today)
        bills = self.svc.bills(today)

        self.t_month.value.setText(_money(cur, s["monthly"]))
        self.t_month.detail.setText(f"{s['count']} recurring bill{'s' if s['count'] != 1 else ''}")
        self.t_month.sub.setText(f"≈ {_money(cur, s['monthly'] * 12)} a year")
        self.t_month.set_chip(f"{len(s['overdue'])} overdue" if s["overdue"] else "", CRIT)

        self.t_split.value.setText(_money(cur, s["per_person"]))
        self.t_split.detail.setText(f"each, split between {people}" if people > 1 else "just you")
        self.t_split.sub.setText("Change the number at the top")

        total = len(bills)
        frac = s["paid_count"] / total if total else 0
        self.t_paid.ring.set(frac, f"{s['paid_count']}/{total}", "paid", GOOD if frac == 1 else ACCENT)
        self.t_paid.value.setText(_money(cur, s["due_this_month"]))
        self.t_paid.detail.setText("still to pay this month" if s["due_this_month"] else "nothing left this month")
        self.t_paid.sub.setText("Resets each period")

        n = s["next"]
        if n:
            days = (n["next_due"] - today).days
            self.t_next.value.setText(n["name"])
            self.t_next.detail.setText(f"{_money(cur, n['amount'])}  ·  {n['next_due']:%a %d %b}")
            self.t_next.sub.setText("today" if days == 0 else "tomorrow" if days == 1 else f"in {days} days")
            self.t_next.set_chip("Soon" if days <= 3 else "", WARN)
        else:
            self.t_next.value.setText("—")
            self.t_next.detail.setText("nothing unpaid with a due date")
            self.t_next.sub.setText("")
            self.t_next.set_chip("", WARN)

        while self.rows.count():
            w = self.rows.takeAt(0).widget()
            if w:
                w.hide()
                w.deleteLater()
        if not bills:
            empty = _lbl("No bills yet. Add rent, electricity, internet, TV, water, school fees…\n"
                         "CypherX totals them per month and reminds you what's due.", MUTED, 12, 500)
            empty.setAlignment(Qt.AlignCenter)
            empty.setMinimumHeight(160)
            self.rows.addWidget(empty)
        order = sorted(bills, key=lambda b: (b["paid"], not b["overdue"],
                                             b["next_due"] or date.max, b["name"]))
        for b in order:
            self.rows.addWidget(BillRow(self, b, cur, today))
        self.rows.addStretch()
        self.count_lbl.setText(f"{total} bill{'s' if total != 1 else ''}")

        cats = s["by_category"]
        self.cats.set_rows([(k, k, v) for k, v in cats.items() if v > 0])
        top = next(iter(cats.items()), None)
        self.cat_note.setText(f"{top[0]} is the biggest monthly cost ({top[1] / s['monthly'] * 100:.0f}%)."
                              if top and s["monthly"] else "One-off bills aren't counted per month.")

    # --------------------------------------------------------------- actions --

    def _people_changed(self, n):
        self.db.set_setting("bills_people", n)
        self.refresh()

    def _add(self):
        dlg = BillDialog(get_currency(self.db), parent=self)
        if dlg.exec() == QDialog.Accepted:
            v = dlg.values()
            self.svc.add_bill(**v)
            self._log(f"Bill added: {v['name']}")
            self.refresh()

    def toggle_paid(self, bill):
        self.svc.set_paid(bill["id"], not bill["paid"])
        self._log(f"{bill['name']} marked {'unpaid' if bill['paid'] else 'paid'}")
        self.refresh()

    def bill_menu(self, bill):
        m = make_menu(self)
        m.addAction(hicon("file_text", "#e2e8f0", 14), "Edit…", lambda: self._edit(bill))
        m.addSeparator()
        m.addAction(hicon("trash", "#f87171", 14), "Delete", lambda: self._delete(bill))
        m.exec(QCursor.pos())

    def _edit(self, bill):
        dlg = BillDialog(get_currency(self.db), bill, self)
        if dlg.exec() == QDialog.Accepted:
            self.svc.update_bill(bill["id"], **dlg.values())
            self.refresh()

    def _delete(self, bill):
        if QMessageBox.question(self, "Delete bill", f"Delete {bill['name']}?") == QMessageBox.Yes:
            self.svc.remove_bill(bill["id"])
            self._log(f"Bill deleted: {bill['name']}")
            self.refresh()

    def _log(self, action):
        try:
            self.db.log_operation("Bills", action, "Success")
        except Exception:
            pass
