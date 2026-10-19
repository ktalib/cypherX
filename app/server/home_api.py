"""
The smart home as seen by the web dashboard and the Telegram bot.

Every method is safe to call from any thread: the work runs on the GUI thread
through GuiBridge, against the same models the desktop pages use, so a switch
flipped on a phone shows up on the desktop straight away (and the other way).
"""
import os
import time
from datetime import date, datetime

from PySide6.QtCore import QBuffer, QByteArray, QIODevice

from app.database import Database
from app.services.budget_service import BudgetService, get_currency

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None


class HomeApi:
    def __init__(self, window, bridge):
        self.w = window
        self.bridge = bridge

    def _gui(self, fn):
        return self.bridge.call(fn)

    def _log(self, action, who):
        try:
            Database.get_instance().log_operation("Remote", f"{action} (by {who})", "Success")
        except Exception:
            pass

    # ------------------------------------------------------------- status --

    def status(self, user=None):
        return self._gui(self._status)

    def _status(self):
        home, cctv = self.w.view_smart_home, self.w.view_cctv
        m, e = home.model, home.energy
        pw = m.power
        cur = pw.get("currency", "₦")
        price = e.price_per_kwh() or pw.get("tariff", 0)
        load = m.load_w()
        names = {r["id"]: r["name"] for r in m.rooms}
        out = e.open_outage()
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        latest = next((ev for ev in reversed(cctv.store.events) if ev.get("snapshot")), None)
        return {
            "time": datetime.now().strftime("%a %d %b %H:%M"),
            "currency": cur,
            "power": {
                "load_w": load, "inverter_w": pw.get("inverter_w", 3000), "source": pw.get("source", "Grid"),
                "battery_pct": pw.get("battery_pct", 100), "runtime_h": m.runtime_hours(),
                "per_hour": load / 1000 * price, "per_day": m.daily_kwh() * price,
            },
            "grid": {"watching": e.grid_detect, "off_since": out["start"] if out else None,
                     "cuts_24h_h": round(e.outage_hours(time.time() - 86400), 2)},
            "meter": {"units_left": e.units_left(), "days_left": e.days_left(), "kwh_per_day": e.burn_rate(),
                      "price": e.price_per_kwh()},
            "rooms": [{"id": r["id"], "name": r["name"], "load_w": m.load_w(r["id"])} for r in m.rooms],
            "devices": [{"id": d["id"], "name": d["name"], "room": names.get(d["room"], ""),
                         "kind": d.get("kind"), "watts": d["device"]["watts"], "on": d["device"]["on"]}
                        for d in sorted(m.devices(), key=lambda d: (d["room"], d["name"]))],
            "security": {
                "armed": bool(cctv.store.config.get("armed")),
                "cameras": [{"id": cid, "name": f.cam["name"], "live": f.running} for cid, f in cctv.feeds.items()],
                "motion_today": sum(1 for ev in cctv.store.events_since(today) if ev["kind"] == "motion"),
                "latest": {"camera": latest["camera_name"], "ts": latest["ts"], "kind": latest["kind"]}
                if latest else None,
            },
        }

    # ------------------------------------------------------------ actions --

    def toggle(self, item_id, who):
        def do():
            home = self.w.view_smart_home
            it = home.model.item(item_id)
            if not it or not it.get("device"):
                raise LookupError("No such appliance")
            home.model.toggle(item_id)
            home.refresh()
            on = home.model.item(item_id)["device"]["on"]
            self._log(f"{it['name']} switched {'ON' if on else 'OFF'}", who)
            return {"id": item_id, "on": on}
        try:
            return self._gui(do)
        except LookupError as e:
            from app.server.web import ApiError
            raise ApiError(404, str(e))

    def all_off(self, who):
        def do():
            self.w.view_smart_home.model.all_off()
            self.w.view_smart_home.refresh()
            self._log("All appliances off (fridge kept on)", who)
            return {"ok": True}
        return self._gui(do)

    def set_armed(self, on, who):
        def do():
            self.w.view_cctv.arm_btn.setChecked(on)
            self._log("CCTV armed" if on else "CCTV disarmed", who)
            return {"armed": on}
        return self._gui(do)

    def add_reading(self, units, who):
        def do():
            home = self.w.view_smart_home
            home.energy.add_reading(units)
            home.refresh_energy()
            self._log(f"Meter reading: {units:g} kWh left", who)
            return {"units_left": home.energy.units_left(), "days_left": home.energy.days_left()}
        return self._gui(do)

    def add_token(self, amount, units, who):
        def do():
            home = self.w.view_smart_home
            home.energy.add_token(amount, units)
            home.refresh_energy()
            self._log(f"Prepaid token: {amount:,.0f} for {units:g} kWh", who)
            return {"units_left": home.energy.units_left()}
        return self._gui(do)

    # ---------------------------------------------------------- snapshots --

    def snapshot_jpeg(self, cam_id=None):
        def do():
            cctv = self.w.view_cctv
            feed = cctv.feeds.get(cam_id) if cam_id else None
            if feed is None:
                feed = next((f for f in cctv.feeds.values() if f.running and f.image is not None), None)
            if feed is not None and feed.running and feed.image is not None and not feed.image.isNull():
                ba = QByteArray()
                buf = QBuffer(ba)
                buf.open(QIODevice.WriteOnly)
                feed.image.save(buf, "JPG", 80)
                return bytes(ba)
            latest = next((ev for ev in reversed(cctv.store.events) if ev.get("snapshot")), None)
            return latest["snapshot"] if latest else None
        result = self._gui(do)
        if isinstance(result, str):                  # a saved file: read it off the GUI thread
            try:
                with open(result, "rb") as f:
                    return f.read()
            except OSError:
                return None
        return result

    def snapshot_caption(self):
        def do():
            cctv = self.w.view_cctv
            live = next((f for f in cctv.feeds.values() if f.running and f.image is not None), None)
            if live:
                return f"{live.cam['name']} · live · {datetime.now():%H:%M:%S}"
            latest = next((ev for ev in reversed(cctv.store.events) if ev.get("snapshot")), None)
            if latest:
                return f"{latest['camera_name']} · {datetime.fromtimestamp(latest['ts']):%a %H:%M}"
            return None
        return self._gui(do)

    # -------------------------------------------------------------- money --

    def bills(self):
        svc = BudgetService(Database.get_instance())
        db = Database.get_instance()
        people = int(db.get_setting("bills_people", 1) or 1)
        s = svc.bill_summary(people=people)
        rows = svc.bills()

        def d(x):
            return x.isoformat() if isinstance(x, date) else x
        return {
            "currency": get_currency(db),
            "monthly": s["monthly"], "per_person": s["per_person"], "people": people,
            "due_this_month": s["due_this_month"], "paid": s["paid_count"], "count": len(rows),
            "bills": [{"name": b["name"], "amount": b["amount"], "frequency": b["frequency"], "paid": b["paid"],
                       "overdue": b["overdue"], "next_due": d(b["next_due"])} for b in rows],
        }

    def groceries(self):
        db = Database.get_instance()
        svc = BudgetService(db)
        lists = svc.lists()
        if not lists:
            return {"currency": get_currency(db), "list": None, "items": []}
        lst = lists[0]
        return {"currency": get_currency(db), "list": {"id": lst["id"], "name": lst["name"]},
                "summary": svc.list_summary(lst["id"]),
                "items": [{"id": i["id"], "name": i["name"], "qty": i["qty"], "total": i["total"],
                           "bought": bool(i["bought"])} for i in svc.items(lst["id"])]}

    def toggle_grocery(self, item_id, who):
        def do():
            svc = BudgetService(Database.get_instance())
            for lst in svc.lists():
                for it in svc.items(lst["id"]):
                    if it["id"] == item_id:
                        svc.update_item(item_id, bought=0 if it["bought"] else 1)
                        if self.w.view_groceries.isVisible():
                            self.w.view_groceries.refresh()
                        return {"id": item_id, "bought": not it["bought"]}
            from app.server.web import ApiError
            raise ApiError(404, "No such item")
        return self._gui(do)

    # ------------------------------------------------------------- server --

    def server(self):
        s = self._gui(lambda: {
            "services": [{"id": x.id, "title": x.title, "status": x.status, "uptime": x.uptime}
                         for x in self.w.services.all()],
            "summary": self.w.services.summary()})
        if psutil is not None:
            root = os.environ.get("SystemDrive", "C:") + "\\" if os.name == "nt" else "/"
            s["cpu"] = psutil.cpu_percent(interval=0.2)
            s["ram"] = psutil.virtual_memory().percent
            s["disk"] = psutil.disk_usage(root).percent
            s["uptime_h"] = round((time.time() - psutil.boot_time()) / 3600, 1)
        return s
