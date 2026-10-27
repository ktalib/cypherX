"""
Fridge — what's inside a fridge that isn't smart: counts, how fast each item
goes, when it runs out, and photo checks counted by an AI (several providers,
free ones included; see app/services/vision_ai.py).
"""
import time
from datetime import datetime

from PySide6.QtCore import Qt, QThread, QTimer, Signal, QUrl
from PySide6.QtGui import QPixmap, QCursor, QDesktopServices, QImage, QColor, QPainter
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton, QFrame, QComboBox, QLineEdit,
    QSpinBox, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QInputDialog, QMessageBox,
    QFileDialog, QDialog, QFormLayout, QDialogButtonBox
)

from app.database import Database
from app.services import vision_ai
from app.services.fridge_service import run_photo_check, changes_text
from app.views.smart_dashboard import StatTile, _card, _action, _lbl
from app.views.smart_dashboard import ACCENT, GOOD, WARN, CRIT, TEXT, SOFT, MUTED, DIM
from app.widgets.home.common import make_menu, hicon

COL_NAME, COL_COUNT, COL_RATE, COL_LEFT, COL_MINUS, COL_PLUS, COL_MORE = range(7)


def _ago(ts):
    s = time.time() - ts
    if s < 90:
        return "just now"
    if s < 3600:
        return f"{s / 60:.0f} min ago"
    if s < 86400:
        return f"{s / 3600:.0f} h ago"
    return datetime.fromtimestamp(ts).strftime("%a %d %b")


def _days(d):
    if d is None:
        return "—"
    if d < 1:
        return "today"
    return f"{d:.0f} day{'s' if round(d) != 1 else ''}"


class CheckWorker(QThread):
    """Runs a photo check off the GUI thread (an AI can take a minute)."""
    done = Signal(object, str)          # result, error

    def __init__(self, store, image, settings, source, parent=None):
        super().__init__(parent)
        self.store, self.image, self.settings, self.source = store, image, settings, source

    def run(self):
        try:
            self.done.emit(run_photo_check(self.store, self.image, self.settings, self.source), "")
        except vision_ai.VisionError as e:
            self.done.emit(None, str(e))
        except Exception as e:  # never let a worker thread crash the app
            self.done.emit(None, f"Unexpected error: {e}")


class TestWorker(QThread):
    done = Signal(str, bool)

    def __init__(self, settings, pid, parent=None):
        super().__init__(parent)
        self.settings, self.pid = settings, pid

    def run(self):
        img = QImage(320, 240, QImage.Format_RGB32)          # a white "shelf" with two "eggs"
        img.fill(QColor("#f1f5f9"))
        p = QPainter(img)
        p.setBrush(QColor("#f5deb3"))
        p.drawEllipse(80, 90, 50, 66)
        p.drawEllipse(170, 90, 50, 66)
        p.end()
        from PySide6.QtCore import QBuffer, QByteArray, QIODevice
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.WriteOnly)
        img.save(buf, "JPG", 85)
        try:
            items, _ = vision_ai.count_with(self.settings, self.pid, bytes(ba), ["Eggs"])
            seen = ", ".join(f"{n} {c}" for n, c in items) or "nothing"
            self.done.emit(f"Connected ✓  The AI answered (test picture: {seen}).", True)
        except vision_ai.VisionError as e:
            self.done.emit(str(e), False)


class AiSettingsDialog(QDialog):
    """Pick the AI that counts fridge photos; keys are kept on this PC only."""

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Fridge — AI that counts photos")
        self.setMinimumWidth(520)
        self.settings = {"provider": settings.get("provider", "none"), "fallback": settings.get("fallback", ""),
                         "providers": {k: dict(v) for k, v in (settings.get("providers") or {}).items()}}
        self.worker = None
        lo = QVBoxLayout(self)
        intro = QLabel("Free options: Google Gemini, OpenRouter and Groq give free API keys with daily limits; "
                       "Ollama runs on this PC with no internet and no key (needs a decent PC). "
                       "Claude and OpenAI are paid and the most accurate.")
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color:{SOFT};")
        lo.addWidget(intro)
        form = QFormLayout()
        self.provider = QComboBox()
        for pid in vision_ai.PROVIDERS:
            self.provider.addItem(vision_ai.label(pid), pid)
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.Password)
        self.model = QLineEdit()
        self.url = QLineEdit()
        self.link = QLabel()
        self.link.setOpenExternalLinks(True)
        self.fallback = QComboBox()
        self.fallback.addItem("None", "")
        for pid in vision_ai.PROVIDERS:
            if pid != "none":
                self.fallback.addItem(vision_ai.label(pid), pid)
        form.addRow("AI", self.provider)
        form.addRow("API key", self.key)
        form.addRow("Model", self.model)
        form.addRow("Address", self.url)
        form.addRow("", self.link)
        form.addRow("If it fails, try", self.fallback)
        lo.addLayout(form)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        lo.addWidget(self.status)
        row = QHBoxLayout()
        self.test_btn = _action("Test", "activity", self._test)
        row.addWidget(self.test_btn)
        row.addStretch()
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        row.addWidget(bb)
        lo.addLayout(row)
        self._current = None
        self.provider.currentIndexChanged.connect(self._picked)
        self.provider.setCurrentIndex(max(0, self.provider.findData(self.settings["provider"])))
        self.fallback.setCurrentIndex(max(0, self.fallback.findData(self.settings["fallback"])))
        self._picked()

    def _stash(self):
        if self._current and self._current != "none":
            self.settings["providers"][self._current] = {
                "key": self.key.text().strip(), "model": self.model.text().strip(), "url": self.url.text().strip()}

    def _picked(self):
        self._stash()
        pid = self.provider.currentData()
        self._current = pid
        base = vision_ai.PROVIDERS[pid]
        mine = self.settings["providers"].get(pid, {})
        self.key.setText(mine.get("key", ""))
        self.model.setText(mine.get("model") or base["model"])
        self.url.setText(mine.get("url") or base["url"])
        none = pid == "none"
        for w in (self.key, self.model, self.url, self.test_btn):
            w.setEnabled(not none)
        self.key.setPlaceholderText("needed" if base["key"] else "not needed")
        self.url.setEnabled(not none and pid != "claude")
        if base["signup"]:
            what = "Download Ollama" if pid == "ollama" else "Get a free key" if pid in vision_ai.FREE else "Get a key"
            self.link.setText(f'<a href="{base["signup"]}" style="color:{ACCENT}">{what}</a>'
                              + (f'  ·  then run <code>ollama pull {base["model"]}</code>' if pid == "ollama" else ""))
        else:
            self.link.setText("")
        self.status.setText("")

    def _test(self):
        self._stash()
        pid = self.provider.currentData()
        self.status.setStyleSheet(f"color:{MUTED};")
        self.status.setText("Asking the AI…")
        self.test_btn.setEnabled(False)
        self.worker = TestWorker(self.result_settings(), pid, self)
        self.worker.done.connect(self._tested)
        self.worker.start()

    def _tested(self, text, ok):
        self.test_btn.setEnabled(True)
        self.status.setStyleSheet(f"color:{GOOD if ok else CRIT};")
        self.status.setText(text)

    def result_settings(self):
        self._stash()
        out = dict(self.settings)
        out["provider"] = self.provider.currentData()
        out["fallback"] = self.fallback.currentData() or ""
        return out

    def _save(self):
        s = self.result_settings()
        ok, why = vision_ai.ready(s)
        if not ok and s["provider"] != "none":
            QMessageBox.warning(self, "AI settings", why)
            return
        self.settings = s
        self.accept()


class FridgeView(QWidget):
    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.db = Database.get_instance()
        self.worker = None
        self._shown_version = -1
        self._filling = False
        self._build()
        self.refresh()
        self._poll = QTimer(self)          # the phone dashboard / Telegram change the stock too
        self._poll.timeout.connect(self._maybe_refresh)
        self._poll.start(3000)

    # ------------------------------------------------------------------- UI --

    def _build(self):
        main = QVBoxLayout(self)
        main.setContentsMargins(14, 14, 14, 14)
        main.setSpacing(12)

        bar = QFrame()
        bar.setObjectName("panel")
        tb = QHBoxLayout(bar)
        tb.setContentsMargins(14, 8, 10, 8)
        t = QLabel("FRIDGE // WHAT'S INSIDE")
        t.setObjectName("section-header")
        tb.addWidget(t)
        tb.addSpacing(12)
        self.ai_lbl = _lbl("", MUTED, 11, 600)
        tb.addWidget(self.ai_lbl)
        tb.addStretch()
        tb.addWidget(_action("AI settings", "settings", self._ai_settings))
        self.cam_btn = _action("From a camera", "camera", self._from_camera)
        tb.addWidget(self.cam_btn)
        self.photo_btn = _action("Check a photo…", "image", self._pick_photo, primary=True)
        tb.addWidget(self.photo_btn)
        main.addWidget(bar)

        tiles = QGridLayout()
        tiles.setHorizontalSpacing(12)
        self.t_items = StatTile("In the fridge", "fridge", ring=False)
        self.t_low = StatTile("Running low", "bell", ring=False)
        self.t_next = StatTile("Runs out next", "timer", ring=False)
        self.t_check = StatTile("Last photo check", "camera", ring=False)
        for i, w in enumerate((self.t_items, self.t_low, self.t_next, self.t_check)):
            tiles.addWidget(w, 0, i)
            tiles.setColumnStretch(i, 1)
        main.addLayout(tiles)

        body = QHBoxLayout()
        body.setSpacing(12)
        card, lo, head = _card("Stock", "check_square")
        head.addWidget(_lbl("double-click a number to correct it", DIM, 10, 500))
        add = QHBoxLayout()
        self.new_name = QLineEdit()
        self.new_name.setPlaceholderText("Add an item to track (e.g. Malt) and press Enter")
        self.new_name.returnPressed.connect(self._add_item)
        self.new_count = QSpinBox()
        self.new_count.setRange(0, 999)
        self.new_count.setPrefix("× ")
        self.new_count.setFixedWidth(80)
        add.addWidget(self.new_name, 1)
        add.addWidget(self.new_count)
        add.addWidget(_action("Add", "plus", self._add_item, primary=True))
        lo.addLayout(add)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["Item", "In fridge", "Uses", "Runs out", "", "", ""])
        self._size_columns()
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked)
        self.table.setShowGrid(False)
        self.table.itemChanged.connect(self._cell_edited)
        lo.addWidget(self.table, 1)
        self.hint = _lbl("Buying eggs or drinks in Groceries adds them here. A photo check corrects the counts; "
                         "between checks the numbers are estimates from how fast you use things.", DIM, 10, 500)
        self.hint.setWordWrap(True)
        lo.addWidget(self.hint)
        body.addWidget(card, 3)

        side, sl, shead = _card("Last photo", "image")
        self.open_btn = QPushButton()
        self.open_btn.setFixedSize(28, 26)
        self.open_btn.setIcon(hicon("folder", "#e2e8f0", 14))
        self.open_btn.setToolTip("Open the photos folder")
        self.open_btn.clicked.connect(lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(self.store.root) + "/photos")))
        shead.addWidget(self.open_btn)
        self.photo = QLabel("No photo yet.\nCheck a photo of the open fridge,\nsend one to the Telegram bot,\n"
                            "or use the phone dashboard.")
        self.photo.setAlignment(Qt.AlignCenter)
        self.photo.setMinimumSize(260, 200)
        self.photo.setStyleSheet("background:#05080d;border-radius:10px;color:#64748b;")
        sl.addWidget(self.photo, 1)
        self.result = _lbl("", SOFT, 11, 500)
        self.result.setWordWrap(True)
        self.result.setTextInteractionFlags(Qt.TextSelectableByMouse)
        sl.addWidget(self.result)
        body.addWidget(side, 2)
        main.addLayout(body, 1)

    # ------------------------------------------------------------ refresh --

    def _maybe_refresh(self):
        if self.store.version != self._shown_version and self.isVisible():
            self.refresh()

    def showEvent(self, e):
        super().showEvent(e)
        self._size_columns()        # the main window's restyle can reset the header to default widths
        self.refresh()

    def _size_columns(self):
        hh = self.table.horizontalHeader()
        hh.setMinimumSectionSize(30)
        hh.setSectionResizeMode(COL_NAME, QHeaderView.Stretch)
        for c, w in ((COL_COUNT, 66), (COL_RATE, 70), (COL_LEFT, 70), (COL_MINUS, 34), (COL_PLUS, 34),
                     (COL_MORE, 34)):
            hh.setSectionResizeMode(c, QHeaderView.Fixed)
            self.table.setColumnWidth(c, w)

    def refresh(self):
        self._shown_version = self.store.version
        items = self.store.items()
        settings = vision_ai.load_settings(self.db)
        pid = settings.get("provider") or "none"
        ok, why = vision_ai.ready(settings)
        self.ai_lbl.setText(f"AI: {vision_ai.PROVIDERS[pid]['title']}" if ok else
                            ("AI: none — count by hand" if pid == "none" else f"AI: {why}"))
        self.ai_lbl.setStyleSheet(f"color:{GOOD if ok else WARN};background:transparent;")

        self._filling = True
        self.table.setRowCount(len(items))
        for r, v in enumerate(items):
            name = QTableWidgetItem(v["name"])
            name.setFlags(Qt.ItemIsEnabled)
            name.setData(Qt.UserRole, v["id"])
            name.setForeground(QColor(CRIT if v["low"] else TEXT))
            name.setToolTip(f"Low at {v['low_at']} · a pack is {v['per_pack']}"
                            + (f" · matches groceries: {v['match']}" if v["match"] else ""))
            self.table.setItem(r, COL_NAME, name)
            est = v["estimate"]
            shown = f"≈ {est:.0f}" if v["rate"] and abs(est - v["count"]) >= 0.5 else f"{v['count']}"
            cnt = QTableWidgetItem(shown)
            cnt.setTextAlignment(Qt.AlignCenter)
            cnt.setForeground(QColor(CRIT if v["low"] else TEXT))
            cnt.setToolTip(f"Last counted {v['count']} ({v['source'] or 'never'}, {_ago(v['updated'])})")
            self.table.setItem(r, COL_COUNT, cnt)
            rate = QTableWidgetItem(f"{v['rate']:.1f}/day" if v["rate"] else "learning")
            rate.setFlags(Qt.ItemIsEnabled)
            rate.setForeground(QColor(SOFT if v["rate"] else DIM))
            rate.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(r, COL_RATE, rate)
            left = QTableWidgetItem(_days(v["days_left"]))
            left.setFlags(Qt.ItemIsEnabled)
            left.setTextAlignment(Qt.AlignCenter)
            left.setForeground(QColor(WARN if v["days_left"] is not None and v["days_left"] < 3 else SOFT))
            self.table.setItem(r, COL_LEFT, left)
            for col, text, tip, slot in ((COL_MINUS, "−", "Took one", lambda _=0, i=v["id"]: self._bump(i, -1)),
                                         (COL_PLUS, "+", "Added one", lambda _=0, i=v["id"]: self._bump(i, 1)),
                                         (COL_MORE, "", "More", lambda _=0, i=v["id"]: self._item_menu(i))):
                b = QPushButton(text)
                if not text:
                    b.setIcon(hicon("more", "#e2e8f0", 13))
                b.setToolTip(tip)
                b.setCursor(Qt.PointingHandCursor)
                b.setStyleSheet("QPushButton{background:transparent;border:none;color:#e2e8f0;font-size:16px;"
                                "font-weight:700;padding:0;min-width:0;}"
                                "QPushButton:hover{background:rgba(255,255,255,0.08);border-radius:6px;}")
                b.clicked.connect(slot)
                self.table.setCellWidget(r, col, b)
        self._filling = False

        low = [v for v in items if v["low"]]
        total = sum(round(v["estimate"]) for v in items)
        self.t_items.value.setText(f"{total:,}")
        self.t_items.detail.setText(f"{len(items)} kind{'s' if len(items) != 1 else ''} of item")
        self.t_items.sub.setText("estimates between photo checks")
        self.t_low.value.setText(str(len(low)))
        self.t_low.detail.setText(", ".join(v["name"] for v in low[:3]) or "nothing")
        self.t_low.sub.setText("added to the shopping list" if low else "")
        self.t_low.set_chip("Low" if low else "", CRIT)
        soon = sorted((v for v in items if v["days_left"] is not None), key=lambda v: v["days_left"])
        if soon:
            self.t_next.value.setText(soon[0]["name"])
            self.t_next.detail.setText(f"in about {_days(soon[0]['days_left'])}")
            self.t_next.sub.setText(f"{soon[0]['rate']:.1f} used a day")
        else:
            self.t_next.value.setText("—")
            self.t_next.detail.setText("learning how fast you use things")
            self.t_next.sub.setText("needs a couple of counts a day apart")
        last = self.store.last_check()
        if last:
            self.t_check.value.setText(_ago(last["ts"]))
            prov = vision_ai.PROVIDERS.get(last["provider"], {}).get("title", "") if last["provider"] else ""
            self.t_check.detail.setText(prov or ("by hand" if last["provider"] == "none" else "not counted"))
            self.t_check.sub.setText(f"{len(last['counts'])} item{'s' if len(last['counts']) != 1 else ''} counted")
            self._show_photo(last.get("photo"))
            if not self.result.text():
                self.result.setText(last.get("note") or "")
        else:
            self.t_check.value.setText("never")
            self.t_check.detail.setText("take a photo of the open fridge")
            self.t_check.sub.setText("")

    def _show_photo(self, path):
        pm = QPixmap(path) if path else QPixmap()
        if pm.isNull():
            return
        self.photo.setPixmap(pm.scaled(self.photo.width(), self.photo.height(), Qt.KeepAspectRatio,
                                       Qt.SmoothTransformation))

    # -------------------------------------------------------------- items --

    def _add_item(self):
        name = self.new_name.text().strip()
        if not name:
            return
        try:
            self.store.add_item(name, self.new_count.value(), low_at=1)
        except ValueError as e:
            QMessageBox.information(self, "Fridge", str(e))
            return
        self.new_name.clear()
        self.new_count.setValue(0)
        self.refresh()

    def _bump(self, item_id, delta):
        self.store.adjust(item_id, delta, source="manual")
        self.refresh()

    def _cell_edited(self, cell):
        if self._filling or cell.column() != COL_COUNT:
            return
        item_id = self.table.item(cell.row(), COL_NAME).data(Qt.UserRole)
        try:
            n = int(float(cell.text().replace("≈", "").strip()))
        except ValueError:
            QTimer.singleShot(0, self.refresh)
            return
        self.store.set_count(item_id, max(0, n), source="manual")
        QTimer.singleShot(0, self.refresh)

    def _item_menu(self, item_id):
        v = self.store.item(item_id)
        if not v:
            return
        m = make_menu(self)
        m.addAction(hicon("file_text", "#e2e8f0", 14), "Rename…", lambda: self._ask_text(v, "name", "Name:"))
        m.addAction(hicon("bell", "#e2e8f0", 14), f"Warn when at or below… ({v['low_at']})",
                    lambda: self._ask_int(v, "low_at", "Warn (and add to the shopping list) at or below:", 0))
        m.addAction(hicon("layers", "#e2e8f0", 14), f"Pack size… ({v['per_pack']})",
                    lambda: self._ask_int(v, "per_pack", "How many in one pack you buy (a crate of eggs = 30):", 1))
        m.addAction(hicon("link", "#e2e8f0", 14), "Grocery names…",
                    lambda: self._ask_text(v, "match", "Grocery list names that count as this item, comma separated\n"
                                                       "(e.g. star, gulder, heineken for Beer):"))
        m.addSeparator()
        m.addAction(hicon("trash", "#f87171", 14), "Stop tracking", lambda: self._remove(v))
        m.exec(QCursor.pos())

    def _ask_text(self, v, field, prompt):
        text, ok = QInputDialog.getText(self, v["name"], prompt, text=v[field])
        if ok:
            self.store.update_item(v["id"], **{field: text})
            self.refresh()

    def _ask_int(self, v, field, prompt, lo):
        n, ok = QInputDialog.getInt(self, v["name"], prompt, v[field], lo, 10000)
        if ok:
            self.store.update_item(v["id"], **{field: n})
            self.refresh()

    def _remove(self, v):
        if QMessageBox.question(self, "Fridge", f"Stop tracking {v['name']}?") == QMessageBox.Yes:
            self.store.remove_item(v["id"])
            self.refresh()

    # ------------------------------------------------------------- checks --

    def _ai_settings(self):
        dlg = AiSettingsDialog(vision_ai.load_settings(self.db), self)
        if dlg.exec() == QDialog.Accepted:
            vision_ai.save_settings(self.db, dlg.settings)
            self.refresh()

    def _pick_photo(self):
        path, _ = QFileDialog.getOpenFileName(self, "Photo of the open fridge", "",
                                              "Pictures (*.jpg *.jpeg *.png *.webp *.bmp)")
        if not path:
            return
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError as e:
            QMessageBox.warning(self, "Fridge", f"Can't open that file: {e}")
            return
        self.check(data, "photo")

    def _from_camera(self):
        win = self.window()
        cctv = getattr(win, "view_cctv", None)
        feeds = [f for f in (cctv.feeds.values() if cctv else []) if f.running and f.image is not None]
        if not feeds:
            QMessageBox.information(self, "Fridge", "No camera is live right now. Start one on the CCTV page "
                                                    "(a phone camera works too), point it at the open fridge, "
                                                    "then try again.")
            return
        m = make_menu(self)
        for f in feeds:
            m.addAction(hicon("camera", "#e2e8f0", 14), f.cam["name"], lambda f=f: self._snap(f))
        m.exec(QCursor.pos())

    def _snap(self, feed):
        from PySide6.QtCore import QBuffer, QByteArray, QIODevice
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.WriteOnly)
        feed.image.save(buf, "JPG", 90)
        self.check(bytes(ba), "camera")

    def check(self, image, source="photo"):
        if self.worker is not None and self.worker.isRunning():
            return
        settings = vision_ai.load_settings(self.db)
        self.photo_btn.setEnabled(False)
        self.cam_btn.setEnabled(False)
        self.photo_btn.setText(" Counting…")
        self.result.setStyleSheet(f"color:{MUTED};background:transparent;")
        self.result.setText("Saving the photo…" if settings.get("provider") == "none" else
                            f"Asking {vision_ai.PROVIDERS[settings['provider']]['title']} to count…")
        self.worker = CheckWorker(self.store, image, settings, source, self)
        self.worker.done.connect(self._checked)
        self.worker.start()

    def _checked(self, res, error):
        self.photo_btn.setEnabled(True)
        self.cam_btn.setEnabled(True)
        self.photo_btn.setText(" Check a photo…")
        if error:
            self.result.setStyleSheet(f"color:{CRIT};background:transparent;")
            self.result.setText(f"Couldn't count this photo: {error}")
        elif res["manual"]:
            self.result.setStyleSheet(f"color:{SOFT};background:transparent;")
            self.result.setText("Photo saved. No AI is set up, so count by hand: double-click a number "
                                "in the list to correct it (AI settings to switch counting on).")
        else:
            self.result.setStyleSheet(f"color:{SOFT};background:transparent;")
            text = changes_text(res["changes"])
            if res["note"]:
                text += f"\n\nAI note: {res['note']}"
            if res["errors"]:
                text += "\n\nFirst choice failed, used the backup: " + "; ".join(res["errors"])
            self.result.setText(f"Counted by {vision_ai.PROVIDERS[res['provider']]['title']}:\n{text}")
        self.refresh()
        try:
            self.db.log_operation("Fridge", "Photo check" + (f" failed: {error}" if error else ""),
                                  "Failed" if error else "Success")
        except Exception:
            pass
