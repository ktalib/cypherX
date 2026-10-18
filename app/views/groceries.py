"""
Groceries — shopping lists with quantity x price, a budget, bought ticks and a
price memory (an item's last price is filled in the next time you add it).
"""
from PySide6.QtCore import Qt, QStringListModel
from PySide6.QtGui import QColor, QFont, QCursor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton, QFrame, QComboBox,
    QLineEdit, QDoubleSpinBox, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QCompleter, QInputDialog, QMessageBox
)

from app.database import Database
from app.services.budget_service import BudgetService, GROCERY_CATEGORIES, get_currency
from app.views.smart_dashboard import StatTile, RoomBars, _card, _action, _lbl
from app.views.smart_dashboard import ACCENT, GOOD, WARN, CRIT, TEXT, SOFT, MUTED, DIM
from app.widgets.home.common import make_menu, hicon

COL_BOUGHT, COL_NAME, COL_CAT, COL_QTY, COL_PRICE, COL_TOTAL, COL_DEL = range(7)


def _money(cur, v):
    return f"{cur}{v:,.0f}"


class GroceriesView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.db = Database.get_instance()
        self.svc = BudgetService(self.db)
        self.list_id = None
        self._filling = False
        self._build()
        self._load_lists()

    # ------------------------------------------------------------------- UI --

    def _build(self):
        main = QVBoxLayout(self)
        main.setContentsMargins(14, 14, 14, 14)
        main.setSpacing(12)

        bar = QFrame()
        bar.setObjectName("panel")
        tb = QHBoxLayout(bar)
        tb.setContentsMargins(14, 8, 10, 8)
        t = QLabel("GROCERIES // SHOPPING LISTS")
        t.setObjectName("section-header")
        tb.addWidget(t)
        tb.addSpacing(12)
        self.list_combo = QComboBox()
        self.list_combo.setMinimumWidth(200)
        self.list_combo.currentIndexChanged.connect(self._list_picked)
        tb.addWidget(self.list_combo)
        more = QPushButton()
        more.setFixedSize(30, 28)
        more.setIcon(hicon("more", "#e2e8f0", 14))
        more.setToolTip("Rename or delete this list")
        more.clicked.connect(self._list_menu)
        tb.addWidget(more)
        tb.addStretch()
        tb.addWidget(_lbl("Budget", MUTED, 11, 600))
        self.budget = QDoubleSpinBox()
        self.budget.setRange(0, 1_000_000_000)
        self.budget.setDecimals(0)
        self.budget.setSingleStep(1000)
        self.budget.setSpecialValueText("no budget")
        self.budget.setGroupSeparatorShown(True)
        self.budget.setMinimumWidth(130)
        self.budget.editingFinished.connect(self._budget_changed)
        tb.addWidget(self.budget)
        tb.addSpacing(8)
        tb.addWidget(_action("New list", "plus", self._new_list, primary=True))
        main.addWidget(bar)

        tiles = QGridLayout()
        tiles.setHorizontalSpacing(12)
        self.t_total = StatTile("List total", "calculator", ring=False)
        self.t_budget = StatTile("Budget", "pie_chart")
        self.t_basket = StatTile("In the basket", "check_square")
        self.t_left = StatTile("Still to buy", "list_music", ring=False)
        for i, w in enumerate((self.t_total, self.t_budget, self.t_basket, self.t_left)):
            tiles.addWidget(w, 0, i)
            tiles.setColumnStretch(i, 1)
        main.addLayout(tiles)

        body = QHBoxLayout()
        body.setSpacing(12)
        card, lo, head = _card("Items", "check_square")
        clear = _action("Clear bought", "trash", self._clear_bought)
        head.addWidget(clear)

        add = QHBoxLayout()
        add.setSpacing(6)
        self.name = QLineEdit()
        self.name.setPlaceholderText("Add an item (e.g. Rice 5kg) and press Enter")
        self.completer_model = QStringListModel()
        comp = QCompleter(self.completer_model, self)
        comp.setCaseSensitivity(Qt.CaseInsensitive)
        comp.setFilterMode(Qt.MatchContains)
        self.name.setCompleter(comp)
        self.name.editingFinished.connect(self._prefill_price)
        comp.activated.connect(lambda _t: self._prefill_price())
        self.name.returnPressed.connect(self._add_item)
        self.qty = QDoubleSpinBox()
        self.qty.setRange(0.1, 10000)
        self.qty.setDecimals(1)
        self.qty.setValue(1)
        self.qty.setPrefix("× ")
        self.qty.setFixedWidth(84)
        self.price = QDoubleSpinBox()
        self.price.setRange(0, 100_000_000)
        self.price.setDecimals(0)
        self.price.setSingleStep(100)
        self.price.setToolTip("Price for one. Remembered for next time.")
        self.price.setFixedWidth(120)
        self.price.setGroupSeparatorShown(True)
        self.cat = QComboBox()
        self.cat.addItems(GROCERY_CATEGORIES)
        lo.addWidget(self.name)                 # full width: item names need the room
        add.addWidget(self.qty)
        add.addWidget(self.price)
        add.addWidget(self.cat, 1)
        add.addWidget(_action("Add", "plus", self._add_item, primary=True))
        lo.addLayout(add)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["", "Item", "Category", "Qty", "Unit price", "Total", ""])
        self.table.setProperty("compact_columns", True)
        hh = self.table.horizontalHeader()
        hh.setMinimumSectionSize(30)
        hh.setSectionResizeMode(COL_NAME, QHeaderView.Stretch)
        for c, w in ((COL_BOUGHT, 34), (COL_CAT, 84), (COL_QTY, 44), (COL_PRICE, 80), (COL_TOTAL, 90), (COL_DEL, 34)):
            hh.setSectionResizeMode(c, QHeaderView.Fixed)
            self.table.setColumnWidth(c, w)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(False)
        self.table.verticalHeader().setDefaultSectionSize(36)
        self.table.itemChanged.connect(self._cell_changed)
        self.table.cellClicked.connect(self._cell_clicked)
        lo.addWidget(self.table, 1)
        hint = _lbl("Click the circle to tick an item off. Double-click a name, quantity or price to edit.",
                    DIM, 10, 500)
        lo.addWidget(hint)
        body.addWidget(card, 1)

        card, lo, _ = _card("Spend by category", "pie_chart")
        card.setFixedWidth(280)
        self.cats = RoomBars(fmt=lambda v: _money(get_currency(self.db), v), share_of="the list",
                             click_hint=None, name_w=84, val_w=84)
        lo.addWidget(self.cats)
        self.cat_note = _lbl("", MUTED, 10, 500)
        self.cat_note.setWordWrap(True)
        lo.addWidget(self.cat_note)
        lo.addStretch()
        body.addWidget(card)
        main.addLayout(body, 1)

    # ----------------------------------------------------------------- lists --

    def _load_lists(self, select=None):
        lists = self.svc.lists()
        if not lists:
            self.svc.add_list("Shopping list")
            lists = self.svc.lists()
        self._filling = True
        self.list_combo.clear()
        for l in lists:
            self.list_combo.addItem(l["name"], l["id"])
        idx = self.list_combo.findData(select) if select else 0
        self.list_combo.setCurrentIndex(max(0, idx))
        self._filling = False
        self._list_picked()

    def _list_picked(self, *_):
        if self._filling:
            return
        self.list_id = self.list_combo.currentData()
        self.refresh()

    def _new_list(self):
        m = make_menu(self)
        m.addAction(hicon("plus", "#e2e8f0", 14), "Empty list", lambda: self._create_list(False))
        m.addAction(hicon("duplicate_finder", "#e2e8f0", 14), "Copy this list (same items, nothing ticked)",
                    lambda: self._create_list(True))
        m.exec(QCursor.pos())

    def _create_list(self, copy):
        name, ok = QInputDialog.getText(self, "New list", "Name (e.g. Weekly shop, Party, Month-end):")
        if ok and name.strip():
            lst = next((l for l in self.svc.lists() if l["id"] == self.list_id), None)
            new_id = self.svc.add_list(name, budget=lst["budget"] if (copy and lst) else 0,
                                       copy_from=self.list_id if copy else None)
            self._load_lists(select=new_id)

    def _list_menu(self):
        m = make_menu(self)
        m.addAction(hicon("file_text", "#e2e8f0", 14), "Rename list…", self._rename_list)
        m.addSeparator()
        m.addAction(hicon("trash", "#f87171", 14), "Delete list", self._delete_list)
        m.exec(QCursor.pos())

    def _rename_list(self):
        name, ok = QInputDialog.getText(self, "Rename list", "Name:", text=self.list_combo.currentText())
        if ok and name.strip():
            self.svc.update_list(self.list_id, name=name.strip())
            self._load_lists(select=self.list_id)

    def _delete_list(self):
        if QMessageBox.question(self, "Delete list", f"Delete '{self.list_combo.currentText()}' and its "
                                                     "items?") == QMessageBox.Yes:
            self.svc.remove_list(self.list_id)
            self._load_lists()

    def _budget_changed(self):
        if self.list_id:
            self.svc.update_list(self.list_id, budget=self.budget.value())
            self.refresh()

    # ----------------------------------------------------------------- items --

    def _prefill_price(self):
        known = self.svc.remembered_price(self.name.text()) if self.name.text().strip() else None
        if known:
            self.price.setValue(known["unit_price"])
            if known.get("category"):
                self.cat.setCurrentText(known["category"])

    def _add_item(self):
        name = self.name.text().strip()
        if not name or not self.list_id:
            return
        self.svc.add_item(self.list_id, name, self.qty.value(), self.price.value(), self.cat.currentText())
        self.name.clear()
        self.qty.setValue(1)
        self.price.setValue(0)
        self.name.setFocus()
        self.refresh()

    def _clear_bought(self):
        if self.list_id:
            self.svc.clear_bought(self.list_id)
            self.refresh()

    def _cell_clicked(self, row, col):
        item = self.table.item(row, COL_NAME)
        if item is None:
            return
        data = item.data(Qt.UserRole)
        if col == COL_BOUGHT:
            self.svc.update_item(data["id"], bought=0 if data["bought"] else 1)
            self.refresh()
        elif col == COL_DEL:
            self.svc.remove_item(data["id"])
            self.refresh()

    def _cell_changed(self, cell):
        if self._filling:
            return
        row = cell.row()
        data = self.table.item(row, COL_NAME).data(Qt.UserRole)
        text = cell.text().replace(",", "").strip()
        cur = get_currency(self.db)
        try:
            if cell.column() == COL_NAME and text:
                self.svc.update_item(data["id"], name=cell.text().strip())
            elif cell.column() == COL_QTY:
                self.svc.update_item(data["id"], qty=max(0.1, float(text.lstrip("×").strip())))
            elif cell.column() == COL_PRICE:
                self.svc.update_item(data["id"], unit_price=max(0.0, float(text.replace(cur, ""))))
        except ValueError:
            pass
        self.refresh()

    # --------------------------------------------------------------- refresh --

    def showEvent(self, e):
        super().showEvent(e)
        self.refresh()

    def refresh(self):
        if not self.list_id:
            return
        cur = get_currency(self.db)
        self.price.setPrefix(cur + " ")
        self.budget.setPrefix(cur + " ")
        s = self.svc.list_summary(self.list_id)
        items = self.svc.items(self.list_id)
        self.completer_model.setStringList(self.svc.known_items())

        self._filling = True
        self.budget.setValue(s["budget"])
        self.table.setRowCount(len(items))
        strike = QFont()
        strike.setStrikeOut(True)
        for r, it in enumerate(items):
            done = bool(it["bought"])
            tick = QTableWidgetItem("●" if done else "○")
            tick.setTextAlignment(Qt.AlignCenter)
            tick.setForeground(QColor(GOOD if done else MUTED))
            tick.setFlags(Qt.ItemIsEnabled)
            tick.setToolTip("Untick" if done else "Tick off — in the basket")
            name = QTableWidgetItem(it["name"])
            name.setData(Qt.UserRole, it)
            cat = QTableWidgetItem(it["category"] or "")
            cat.setFlags(Qt.ItemIsEnabled)
            qty = QTableWidgetItem(f"{it['qty']:g}")
            qty.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            price = QTableWidgetItem(f"{it['unit_price']:,.0f}")
            price.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            total = QTableWidgetItem(_money(cur, it["total"]))
            total.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            total.setFlags(Qt.ItemIsEnabled)
            dele = QTableWidgetItem("✕")
            dele.setTextAlignment(Qt.AlignCenter)
            dele.setForeground(QColor("#f87171"))
            dele.setFlags(Qt.ItemIsEnabled)
            dele.setToolTip("Remove item")
            for c, w in enumerate((tick, name, cat, qty, price, total, dele)):
                if done and c in (COL_NAME, COL_CAT, COL_QTY, COL_PRICE, COL_TOTAL):
                    w.setForeground(QColor(DIM))
                    if c == COL_NAME:
                        w.setFont(strike)
                elif c in (COL_NAME, COL_TOTAL):
                    w.setForeground(QColor(TEXT))
                elif c in (COL_CAT, COL_QTY, COL_PRICE):
                    w.setForeground(QColor(SOFT))
                self.table.setItem(r, c, w)
        self._filling = False

        self.t_total.value.setText(_money(cur, s["total"]))
        self.t_total.detail.setText(f"{s['count']} item{'s' if s['count'] != 1 else ''}")
        self.t_total.sub.setText(self.list_combo.currentText())

        if s["budget"]:
            used = s["total"] / s["budget"]
            over = s["left_in_budget"] < 0
            self.t_budget.ring.set(min(1.0, used), f"{used * 100:.0f}%", "of budget",
                                   CRIT if over else WARN if used > 0.9 else ACCENT)
            self.t_budget.value.setText(_money(cur, abs(s["left_in_budget"])))
            self.t_budget.detail.setText("over budget" if over else "left in the budget")
            self.t_budget.sub.setText(f"Budget {_money(cur, s['budget'])}")
            self.t_budget.set_chip("Over" if over else "", CRIT)
        else:
            self.t_budget.ring.set(0, "—", "no budget", DIM)
            self.t_budget.value.setText("No budget")
            self.t_budget.detail.setText("Set one at the top right")
            self.t_budget.sub.setText("")
            self.t_budget.set_chip("", CRIT)

        frac = s["bought_count"] / s["count"] if s["count"] else 0
        self.t_basket.ring.set(frac, f"{s['bought_count']}/{s['count']}", "items", GOOD if frac == 1 else ACCENT)
        self.t_basket.value.setText(_money(cur, s["bought"]))
        self.t_basket.detail.setText("spent so far" if s["bought"] else "nothing ticked yet")
        self.t_basket.sub.setText("All done" if s["count"] and frac == 1 else "")

        self.t_left.value.setText(_money(cur, s["remaining"]))
        left = s["count"] - s["bought_count"]
        self.t_left.detail.setText(f"{left} item{'s' if left != 1 else ''} to buy")
        self.t_left.sub.setText("")

        cats = s["by_category"]
        self.cats.set_rows([(k, k, v) for k, v in cats.items() if v > 0])
        top = next(iter(cats.items()), None)
        self.cat_note.setText(f"{top[0]} is the biggest part of this list ({top[1] / s['total'] * 100:.0f}%)."
                              if top and s["total"] else "Add items with prices to see the split.")
