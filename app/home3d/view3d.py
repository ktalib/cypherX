"""
House3DView — a small software 3D renderer (QPainter only, no OpenGL needed).

  • perspective camera that orbits (left-drag), pans (right / middle-drag),
    zooms (wheel) and resets (double-click)
  • walls and floors textured with crops of the real room photos
    (perspective-correct via QTransform.quadToQuad)
  • dollhouse cut-away: walls facing the camera drop to a low kerb so you can
    see inside; walls between rooms are half height
  • hover a device to highlight it, click to switch it on / off
  • animated power-flow lines from the power hub to every running device,
    spinning fan blades, glowing lights and TV screen
"""
import math
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QPointF, QRectF, Signal, QVariantAnimation, QEasingCurve
from PySide6.QtGui import (
    QPainter, QColor, QPen, QPolygonF, QTransform, QImage, QPixmap, QFont,
    QRadialGradient, QLinearGradient, QPainterPath
)
from PySide6.QtWidgets import QWidget

from app.home3d.model import WALL_H

ASSETS = Path(__file__).resolve().parent.parent / "assets" / "home"
WALL_T = 0.06            # wall thickness (each room draws its own skin)
LOW_H = 0.22             # height of cut-away walls
MID_H = 1.05             # walls between rooms
DOOR_H = 2.15
LIGHT = (0.35, 0.9, 0.55)
_n = math.sqrt(sum(c * c for c in LIGHT))
LIGHT = tuple(c / _n for c in LIGHT)


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _norm(a):
    l = math.sqrt(_dot(a, a)) or 1.0
    return (a[0] / l, a[1] / l, a[2] / l)


class Face:
    __slots__ = ("pts", "normal", "color", "tex", "reps", "item", "layer", "special", "edge")

    def __init__(self, pts, normal, color, tex=None, reps=(1, 1), item=None, layer=1,
                 special=None, edge=True):
        self.pts, self.normal, self.color = pts, normal, QColor(color)
        self.tex, self.reps, self.item, self.layer = tex, reps, item, layer
        self.special, self.edge = special, edge


def box(x0, y0, z0, x1, y1, z1, color, item=None, tex=None, skip=(), special=None):
    """Axis-aligned box; tex maps face name -> (texture, reps_u, reps_v)."""
    tex = tex or {}
    faces = {
        "top": ([(x0, y1, z0), (x1, y1, z0), (x1, y1, z1), (x0, y1, z1)], (0, 1, 0)),
        "front": ([(x0, y1, z1), (x1, y1, z1), (x1, y0, z1), (x0, y0, z1)], (0, 0, 1)),
        "back": ([(x1, y1, z0), (x0, y1, z0), (x0, y0, z0), (x1, y0, z0)], (0, 0, -1)),
        "left": ([(x0, y1, z0), (x0, y1, z1), (x0, y0, z1), (x0, y0, z0)], (-1, 0, 0)),
        "right": ([(x1, y1, z1), (x1, y1, z0), (x1, y0, z0), (x1, y0, z1)], (1, 0, 0)),
    }
    out = []
    for name, (pts, n) in faces.items():
        if name in skip:
            continue
        t = tex.get(name)
        out.append(Face(pts, n, color, t[0] if t else None, (t[1], t[2]) if t else (1, 1), item,
                        special=special.get(name) if isinstance(special, dict) else None))
    return out


# ---------------------------------------------------------------------------
#  Furniture builders — each returns (faces, anchor point for labels / flows)
# ---------------------------------------------------------------------------

def _wall_plane(room, side, inset):
    if side == "north":
        return room["z"] + inset
    if side == "south":
        return room["z"] + room["d"] - inset
    if side == "west":
        return room["x"] + inset
    return room["x"] + room["w"] - inset


def build_item(it, room):
    k = it["kind"]
    x, z, w, d, h = it["x"], it["z"], it.get("w", 0.4), it.get("d", 0.4), it.get("h", 0.4)
    y = it.get("y", 0.0)
    iid = it["id"]
    col = it.get("color", "#555b66")
    on = bool(it.get("device", {}).get("on")) if it.get("device") else False

    if k == "tv_wall":
        zw = _wall_plane(room, "north", WALL_T) if room else z
        px0, px1 = x - 0.3, x + w + 0.3
        faces = box(px0, y - 0.35, zw, px1, y + h + 0.3, zw + 0.03, "#8a6a4a", None,
                    {"front": ("slat_panel", 1, 1)})
        faces += box(x, y, zw + 0.03, x + w, y + h, zw + 0.09, "#0b0c10", iid,
                     special={"front": "screen_on" if on else "screen_off"})
        return faces, (x + w / 2, y + h / 2, zw + 0.1)
    if k == "cabinet":
        faces = box(x, y, z, x + w, y + h, z + d, col, iid if it.get("device") else None)
        return faces, (x + w / 2, y + h, z + d / 2)
    if k in ("small_box", "appliance"):
        faces = box(x, y, z, x + w, y + h, z + d, col, iid)
        return faces, (x + w / 2, y + h, z + d / 2)
    if k == "sofa_l":
        seat = 0.42
        faces = box(x, 0, z, x + w, seat, z + d, col, iid)
        faces += box(x, seat, z + d - 0.22, x + w, h, z + d, col, iid)                # back
        faces += box(x - 0.18, 0, z, x, 0.6, z + d, col, iid)                        # arm
        cx0 = x + w - 0.85
        faces += box(cx0, 0, z - 1.35, x + w, seat, z, col, iid)                      # chaise
        faces += box(x + w - 0.22, seat, z - 1.35, x + w, h, z, col, iid)
        faces += box(cx0 - 0.05, seat, z - 1.0, cx0 + 0.55, seat + 0.12, z - 0.55, "#2b2fd0", iid,
                     {"top": ("pillow_blue", 1, 1)})                                  # LV pillow
        for i in range(3):
            faces += box(x + 0.25 + i * 0.85, seat, z + d - 0.4, x + 0.85 + i * 0.85, seat + 0.32,
                         z + d - 0.22, "#33343d", iid)                                # cushions
        return faces, (x + w / 2, h, z + d / 2)
    if k == "coffee_table":
        faces = box(x, 0.06, z, x + w, h - 0.03, z + d, col, iid)
        faces += box(x - 0.01, h - 0.03, z - 0.01, x + w + 0.01, h, z + d + 0.01, "#0d0e12", iid)
        return faces, (x + w / 2, h, z + d / 2)
    if k == "fan":
        cx, cz = x + w / 2, z + d / 2
        faces = box(cx - 0.2, 0, cz - 0.2, cx + 0.2, 0.04, cz + 0.2, "#151619", iid)
        faces += box(cx - 0.02, 0.04, cz - 0.02, cx + 0.02, h - 0.2, cz + 0.02, "#202226", iid)
        faces += box(cx - 0.22, h - 0.42, cz - 0.05, cx + 0.22, h, cz + 0.05, "#1a1b1f", iid)
        return faces, (cx, h - 0.21, cz + 0.06)
    if k == "ceiling_light":
        yy = WALL_H - 0.06
        faces = box(x - w / 2, yy, z - d / 2, x + w / 2, yy + 0.04, z + d / 2,
                    "#fff3c4" if on else "#d7d7d7", iid)
        return faces, (x, yy, z)
    if k == "power_hub":
        faces = box(x, 0, z, x + w, h, z + d, "#1b2433", iid)
        faces += box(x + 0.05, h * 0.55, z + d, x + w - 0.05, h * 0.62, z + d + 0.005, "#7fd4ff", iid)
        return faces, (x + w / 2, h, z + d / 2)
    if k == "bed":
        faces = box(x, 0, z, x + w, 0.32, z + d, "#121317", iid)
        faces += box(x + 0.04, 0.32, z + 0.12, x + w - 0.04, h, z + d - 0.03, "#2a2fd6", iid,
                     {"top": ("bedspread", 1, 1), "front": ("bedspread", 2, 0.4),
                      "right": ("bedspread", 2, 0.4), "left": ("bedspread", 2, 0.4)})
        faces += box(x - 0.02, 0, z, x + w + 0.02, 1.15, z + 0.12, "#101114", iid)        # headboard
        for i in range(2):
            px = x + 0.25 + i * (w / 2)
            faces += box(px, h, z + 0.2, px + w / 2 - 0.45, h + 0.14, z + 0.62, "#2a2fd6", iid,
                         {"top": ("pillow_blue", 1, 1)})
        return faces, (x + w / 2, h, z + d / 2)
    if k == "wardrobe":
        faces = box(x, 0, z, x + w, h, z + d, "#26242c", iid, {"back": ("wardrobe", 1, 1)})
        return faces, (x + w / 2, h, z + d / 2)
    if k == "counter":
        faces = box(x, 0, z, x + w, h - 0.04, z + d, "#d9dde2", iid,
                    {"right": ("kitchen_counter", 3, 1)})
        faces += box(x - 0.01, h - 0.04, z - 0.01, x + w + 0.03, h, z + d + 0.01, "#a9c3d6", iid)
        return faces, (x + w / 2, h, z + d / 2)
    if k == "fridge":
        faces = box(x, 0, z, x + w, h, z + d, "#8e9298", iid)
        faces += box(x + w, 0.55, z + 0.08, x + w + 0.01, 0.57, z + d - 0.08, "#4b4e54", iid)  # door split
        faces += box(x + w, 0.75, z + 0.06, x + w + 0.03, 1.15, z + 0.1, "#2e3035", iid)        # handle
        return faces, (x + w / 2, h, z + d / 2)
    return [], (x, y, z)


# ---------------------------------------------------------------------------
#  The view
# ---------------------------------------------------------------------------

class House3DView(QWidget):
    device_clicked = Signal(str)
    hover_changed = Signal(str)          # item id or ""

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model
        self.setMouseTracking(True)
        self.setMinimumSize(480, 360)
        self.setFocusPolicy(Qt.StrongFocus)
        self.mode = "cutaway"            # cutaway | walls | plan
        self.show_labels = True
        self.show_device_labels = True
        self.show_flows = True
        self._tex = {}
        self._tiled = {}
        self._cache = None
        self._hit = []                   # (QPolygonF, item id) in draw order
        self._anchors = {}               # item id -> 3D anchor
        self._hover = ""
        self._drag = None
        self._phase = 0.0
        self.reset_camera(animate=False)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)
        self._cam_anim = None
        self.bg = (QColor(18, 30, 46), QColor(5, 9, 15))     # backdrop: centre, edges
        self.grid_color = QColor(127, 212, 255, 22)          # floor grid lines
        # label colours: rooms, appliances that are on, and the outline (cool by default)
        self.tag_colors = {"room_bg": QColor(10, 16, 26, 200), "room_fg": QColor(223, 243, 255),
                           "on_bg": QColor(8, 40, 30, 215), "on_fg": QColor(150, 255, 200),
                           "on_dot": QColor(110, 240, 170), "line": QColor(127, 212, 255)}

    # ------------------------------------------------------------- camera --

    def _bounds(self):
        rs = self.model.rooms
        x0 = min(r["x"] for r in rs)
        x1 = max(r["x"] + r["w"] for r in rs)
        z0 = min(r["z"] for r in rs)
        z1 = max(r["z"] + r["d"] for r in rs)
        return x0, z0, x1, z1

    def reset_camera(self, animate=True):
        x0, z0, x1, z1 = self._bounds()
        target = ((x0 + x1) / 2, 0.6, (z0 + z1) / 2)
        span = max(x1 - x0, z1 - z0)
        pitch = 88.0 if self.mode == "plan" else 52.0
        self._go(target, -28.0 if self.mode != "plan" else 0.0, pitch, span * 1.3, animate)

    def focus_room(self, room_id):
        r = self.model.room(room_id)
        if r:
            span = max(r["w"], r["d"])
            self._go((r["x"] + r["w"] / 2, 0.6, r["z"] + r["d"] / 2), self.yaw, max(40.0, self.pitch),
                     span * 1.9, True)

    def _go(self, target, yaw, pitch, dist, animate):
        if not animate or not hasattr(self, "target"):
            self.target, self.yaw, self.pitch, self.dist = target, yaw, pitch, dist
            self.invalidate()
            return
        start = (self.target, self.yaw, self.pitch, self.dist)
        anim = QVariantAnimation(self)
        anim.setDuration(550)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.InOutCubic)

        def step(t):
            t = float(t)
            (st, sy, sp, sd) = start
            self.target = tuple(a + (b - a) * t for a, b in zip(st, target))
            self.yaw = sy + (yaw - sy) * t
            self.pitch = sp + (pitch - sp) * t
            self.dist = sd + (dist - sd) * t
            self.invalidate()

        anim.valueChanged.connect(step)
        anim.start()
        self._cam_anim = anim

    def use_warm_theme(self):
        """The warm home look: graphite backdrop, orange labels."""
        self.bg = (QColor(46, 36, 28), QColor(14, 12, 11))
        self.grid_color = QColor(255, 170, 110, 18)
        self.tag_colors = {"room_bg": QColor(24, 20, 17, 215), "room_fg": QColor(250, 250, 249),
                           "on_bg": QColor(58, 30, 12, 225), "on_fg": QColor(255, 207, 170),
                           "on_dot": QColor(255, 122, 26), "line": QColor(255, 222, 196)}
        self.invalidate()

    def set_mode(self, mode):
        self.mode = mode
        self.reset_camera()

    def invalidate(self):
        self._cache = None
        self.update()

    def _basis(self):
        yaw, pitch = math.radians(self.yaw), math.radians(self.pitch)
        tx, ty, tz = self.target
        eye = (tx + self.dist * math.cos(pitch) * math.sin(yaw),
               ty + self.dist * math.sin(pitch),
               tz + self.dist * math.cos(pitch) * math.cos(yaw))
        f = _norm(_sub(self.target, eye))
        r = _norm(_cross(f, (0, 1, 0)))
        u = _cross(r, f)
        return eye, f, r, u

    def _project_fn(self):
        eye, f, r, u = self._basis()
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        scale = min(w, h) * 1.15

        def proj(p):
            v = (p[0] - eye[0], p[1] - eye[1], p[2] - eye[2])
            zc = v[0] * f[0] + v[1] * f[1] + v[2] * f[2]
            if zc < 0.15:
                return None
            xc = v[0] * r[0] + v[1] * r[1] + v[2] * r[2]
            yc = v[0] * u[0] + v[1] * u[1] + v[2] * u[2]
            return QPointF(cx + scale * xc / zc, cy - scale * yc / zc), zc

        return proj, eye

    # ------------------------------------------------------------ textures --

    def _texture(self, name):
        if name not in self._tex:
            img = QImage(str(ASSETS / f"{name}.jpg"))
            self._tex[name] = img if not img.isNull() else None
        return self._tex[name]

    def _tiled_tex(self, name, ru, rv):
        ru, rv = max(1, round(ru)), max(1, round(rv))
        key = (name, ru, rv)
        if key not in self._tiled:
            src = self._texture(name)
            if src is None:
                self._tiled[key] = None
            else:
                tw = max(32, min(src.width(), 1024 // ru))
                th = max(32, min(src.height(), 1024 // rv))
                tile = src.scaled(tw, th, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
                img = QImage(tw * ru, th * rv, QImage.Format_RGB32)
                p = QPainter(img)
                for i in range(ru):
                    for j in range(rv):
                        p.drawImage(i * tw, j * th, tile)
                p.end()
                self._tiled[key] = img
        return self._tiled[key]

    # --------------------------------------------------------------- scene --

    def _is_interior(self, room, side):
        """True when another room touches this wall."""
        for o in self.model.rooms:
            if o is room:
                continue
            if side == "north" and abs(o["z"] + o["d"] - room["z"]) < 0.05:
                if o["x"] < room["x"] + room["w"] and o["x"] + o["w"] > room["x"]:
                    return True
            if side == "south" and abs(o["z"] - (room["z"] + room["d"])) < 0.05:
                if o["x"] < room["x"] + room["w"] and o["x"] + o["w"] > room["x"]:
                    return True
            if side == "west" and abs(o["x"] + o["w"] - room["x"]) < 0.05:
                if o["z"] < room["z"] + room["d"] and o["z"] + o["d"] > room["z"]:
                    return True
            if side == "east" and abs(o["x"] - (room["x"] + room["w"])) < 0.05:
                if o["z"] < room["z"] + room["d"] and o["z"] + o["d"] > room["z"]:
                    return True
        return False

    def _door_spans(self, room, side):
        """Door openings on a wall, as (start, end) distances along the wall's tl→tr direction."""
        x0, z0 = room["x"], room["z"]
        x1, z1 = x0 + room["w"], z0 + room["d"]
        spans = []
        for it in self.model.items:
            if not it.get("door") or it.get("room") != room["id"] or it.get("wall") != side:
                continue
            if side in ("north", "south"):
                a, b = it["x"] - x0, it["x"] + it["w"] - x0
                if side == "south":
                    a, b = room["w"] - b, room["w"] - a
            else:
                a, b = it["z"] - z0, it["z"] + it["w"] - z0
                if side == "west":
                    a, b = room["d"] - b, room["d"] - a
            spans.append((max(0.0, a), min(b, room["w"] if side in ("north", "south") else room["d"])))
        return spans

    def _build_scene(self, eye):
        faces = []
        self._anchors = {}
        self._tall = {}                  # (room, side) -> height of walls we look at
        for room in self.model.rooms:
            x0, z0 = room["x"], room["z"]
            x1, z1 = x0 + room["w"], z0 + room["d"]
            tile = room.get("floor_tile", 1.0)
            faces.append(Face([(x0, 0, z0), (x1, 0, z0), (x1, 0, z1), (x0, 0, z1)], (0, 1, 0),
                              "#5a4a3a", room.get("floor"), (room["w"] / tile, room["d"] / tile),
                              None, layer=0))
            t = WALL_T
            walls = {  # side: inner-face corners tl, tr at height H (bottom is y=0), inward normal
                "north": ((x0, z0 + t), (x1, z0 + t), (0, 0, 1)),
                "south": ((x1, z1 - t), (x0, z1 - t), (0, 0, -1)),
                "west": ((x0 + t, z1), (x0 + t, z0), (1, 0, 0)),
                "east": ((x1 - t, z0), (x1 - t, z1), (-1, 0, 0)),
            }
            for side, ((ax, az), (bx, bz), n) in walls.items():
                to_eye = (eye[0] - (ax + bx) / 2, 0, eye[2] - (az + bz) / 2)
                facing = _dot(n, to_eye) > 0              # we see the inner face → far wall
                interior = self._is_interior(room, side)
                if self.mode == "plan":
                    H = LOW_H
                elif self.mode == "walls":
                    H = WALL_H if facing else (MID_H if interior else LOW_H)
                else:
                    H = (MID_H if interior else WALL_H) if facing else LOW_H
                if facing:
                    self._tall[(room["id"], side)] = H
                length = math.hypot(bx - ax, bz - az)
                dado = min(room.get("dado_h", 1.2), H)
                ux, uz = (bx - ax) / length, (bz - az) / length

                def at(s_, y_):
                    return (ax + ux * s_, y_, az + uz * s_)

                # split the wall around door openings on this side
                gaps = sorted(self._door_spans(room, side))
                segs, cur = [], 0.0
                for g0, g1 in gaps:
                    if g0 > cur:
                        segs.append((cur, g0, 0.0))
                    segs.append((g0, g1, DOOR_H))            # lintel above the door
                    cur = g1
                if cur < length:
                    segs.append((cur, length, 0.0))
                ox, oz = -n[0] * t, -n[2] * t
                for s0, s1, ybase in segs:
                    if ybase >= H:
                        # doorway in a cut-down wall: mark the threshold on the floor
                        faces.append(Face([at(s0, 0.012), at(s1, 0.012),
                                           (at(s1, 0.012)[0] + ox, 0.012, at(s1, 0.012)[2] + oz),
                                           (at(s0, 0.012)[0] + ox, 0.012, at(s0, 0.012)[2] + oz)],
                                          (0, 1, 0), "#8a6a48", layer=0, edge=False))
                        continue
                    seg_len = s1 - s0
                    lo = max(ybase, 0.0)
                    if lo < dado:
                        faces.append(Face([at(s0, dado), at(s1, dado), at(s1, lo), at(s0, lo)], n,
                                          "#cfcfd4", room.get("dado") if lo == 0 else None,
                                          (max(1, seg_len / 1.1), 1), None))
                    top_lo = max(dado, lo)
                    if H > top_lo:
                        faces.append(Face([at(s0, H), at(s1, H), at(s1, top_lo), at(s0, top_lo)], n,
                                          "#e6d891", room.get("paint"), (max(1, seg_len / 2.2), 1), None))
                    faces.append(Face([(at(s0, H)[0] + ox, H, at(s0, H)[2] + oz),
                                       (at(s1, H)[0] + ox, H, at(s1, H)[2] + oz), at(s1, H), at(s0, H)],
                                      (0, 1, 0), "#f2efe6", edge=False))
                    faces.append(Face([(at(s1, H)[0] + ox, H, at(s1, H)[2] + oz),
                                       (at(s0, H)[0] + ox, H, at(s0, H)[2] + oz),
                                       (at(s0, lo)[0] + ox, lo, at(s0, lo)[2] + oz),
                                       (at(s1, lo)[0] + ox, lo, at(s1, lo)[2] + oz)],
                                      (-n[0], 0, -n[2]), "#d8cf9e"))
                    if ybase > 0:                             # door jamb sides
                        faces.append(Face([at(s0, H), (at(s0, H)[0] + ox, H, at(s0, H)[2] + oz),
                                           (at(s0, ybase)[0] + ox, ybase, at(s0, ybase)[2] + oz),
                                           at(s0, ybase)], (0, -1, 0), "#cfc6a0", edge=False))

        rooms = {r["id"]: r for r in self.model.rooms}
        for it in self.model.items:
            room = rooms.get(it.get("room"))
            if it["kind"] == "decal":
                side = it.get("wall", "north")
                y_top = it.get("y", 0.0) + it["h"]
                if room is None or self._tall.get((room["id"], side), 0) < y_top:
                    continue                              # wall cut away / too low for this decal
                p = _wall_plane(room, side, WALL_T + 0.012)
                y0, y1 = it.get("y", 0.0), it.get("y", 0.0) + it["h"]
                if side in ("north", "south"):
                    a, b = it["x"], it["x"] + it["w"]
                    tl, tr = ((a, p), (b, p)) if side == "north" else ((b, p), (a, p))
                    pts = [(tl[0], y1, tl[1]), (tr[0], y1, tr[1]), (tr[0], y0, tr[1]), (tl[0], y0, tl[1])]
                    n = (0, 0, 1) if side == "north" else (0, 0, -1)
                else:
                    a, b = it["z"], it["z"] + it["w"]
                    tl, tr = ((p, b), (p, a)) if side == "west" else ((p, a), (p, b))
                    pts = [(tl[0], y1, tl[1]), (tr[0], y1, tr[1]), (tr[0], y0, tr[1]), (tl[0], y0, tl[1])]
                    n = (1, 0, 0) if side == "west" else (-1, 0, 0)
                faces.append(Face(pts, n, "#333", it.get("tex"), (1, 1), None))
                continue
            fs, anchor = build_item(it, room)
            if room is not None and self.mode == "cutaway" and it.get("h", 0) > 1.2:
                cx, cz = it["x"] + it.get("w", 0) / 2, it["z"] + it.get("d", 0) / 2
                gaps = {"north": cz - room["z"], "south": room["z"] + room["d"] - cz,
                        "west": cx - room["x"], "east": room["x"] + room["w"] - cx}
                near = min(gaps, key=gaps.get)
                if (room["id"], near) not in self._tall:     # against a cut-away wall: see through it
                    for fc in fs:
                        fc.special = "ghost"
            faces.extend(fs)
            self._anchors[it["id"]] = anchor
        return faces

    # ----------------------------------------------------------- rendering --

    def _render_static(self):
        dpr = self.devicePixelRatioF()
        pm = QPixmap(int(self.width() * dpr), int(self.height() * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, self._drag is None)
        proj, eye = self._project_fn()
        self._proj, self._eye = proj, eye
        self._paint_ground(p, proj)

        faces = self._build_scene(eye)
        drawable = []
        for fc in faces:
            centre = tuple(sum(c[i] for c in fc.pts) / 4 for i in range(3))
            to_eye = _sub(eye, centre)
            if fc.layer > 0 and _dot(fc.normal, to_eye) <= 0:
                continue                                      # back-face
            pts = [proj(q) for q in fc.pts]
            if any(q is None for q in pts):
                continue
            depth = math.sqrt(_dot(to_eye, to_eye))
            drawable.append((fc.layer, -depth, fc, [q[0] for q in pts]))
        drawable.sort(key=lambda d: (d[0], d[1]))

        self._hit = []
        for _, _, fc, pts in drawable:
            poly = QPolygonF(pts)
            light = 0.6 + 0.4 * max(0.0, _dot(fc.normal, LIGHT))
            if fc.layer == 0:
                light = 0.95
            img = self._tiled_tex(fc.tex, *fc.reps) if fc.tex else None
            if fc.special == "ghost":
                c = QColor(fc.color)
                c.setAlpha(70)
                edge = QColor(self.tag_colors["line"])
                edge.setAlpha(90)
                p.setPen(QPen(edge, 1))
                p.setBrush(c)
                p.drawPolygon(poly)
                if fc.item:
                    self._hit.append((poly, fc.item))
                continue
            if fc.special == "screen_on":
                g = QLinearGradient(pts[0], pts[2])
                g.setColorAt(0, QColor(70, 150, 255))
                g.setColorAt(1, QColor(20, 40, 120))
                p.setPen(Qt.NoPen)
                p.setBrush(g)
                p.drawPolygon(poly)
            elif img is not None:
                src = QPolygonF([QPointF(0, 0), QPointF(img.width(), 0),
                                 QPointF(img.width(), img.height()), QPointF(0, img.height())])
                t = QTransform()
                if QTransform.quadToQuad(src, poly, t):
                    p.save()
                    p.setTransform(t, True)
                    p.drawImage(0, 0, img)
                    p.restore()
                else:
                    p.setPen(Qt.NoPen)
                    p.setBrush(fc.color)
                    p.drawPolygon(poly)
                if light < 0.999:
                    p.setPen(Qt.NoPen)
                    p.setBrush(QColor(0, 0, 0, int((1 - light) * 210)))
                    p.drawPolygon(poly)
            else:
                c = QColor(fc.color)
                c = QColor(int(c.red() * light), int(c.green() * light), int(c.blue() * light))
                p.setPen(Qt.NoPen)
                p.setBrush(c)
                p.drawPolygon(poly)
            if fc.edge:
                p.setPen(QPen(QColor(0, 0, 0, 55), 1))
                p.setBrush(Qt.NoBrush)
                p.drawPolygon(poly)
            if fc.item:
                self._hit.append((poly, fc.item))
        p.end()
        self._cache = pm

    def _paint_ground(self, p, proj):
        x0, z0, x1, z1 = self._bounds()
        p.setPen(QPen(self.grid_color, 1))
        for gx in range(int(x0) - 3, int(x1) + 4):
            a, b = proj((gx, -0.01, z0 - 3)), proj((gx, -0.01, z1 + 3))
            if a and b:
                p.drawLine(a[0], b[0])
        for gz in range(int(z0) - 3, int(z1) + 4):
            a, b = proj((x0 - 3, -0.01, gz)), proj((x1 + 3, -0.01, gz))
            if a and b:
                p.drawLine(a[0], b[0])

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        g = QRadialGradient(self.width() / 2, self.height() * 0.45, max(self.width(), self.height()) * 0.8)
        g.setColorAt(0, self.bg[0])
        g.setColorAt(1, self.bg[1])
        p.fillRect(self.rect(), g)
        if self._cache is None or self._cache.size() / max(1.0, self._cache.devicePixelRatio()) != self.size():
            self._render_static()
        p.drawPixmap(0, 0, self._cache)
        self._paint_dynamic(p)

    def _anchor2d(self, item_id):
        a = self._anchors.get(item_id)
        if a is None:
            return None
        r = self._proj(a)
        return r[0] if r else None

    def _paint_dynamic(self, p):
        model = self.model
        proj = self._proj
        # light glows
        for d in model.devices():
            if d["kind"] == "ceiling_light" and d["device"]["on"]:
                room = model.room(d["room"])
                fl = proj((d["x"], 0.0, d["z"]))
                lp = proj((d["x"], WALL_H - 0.08, d["z"]))
                if fl and room:
                    rr = proj((d["x"] + room["w"] / 2, 0.0, d["z"]))
                    rad = abs(rr[0].x() - fl[0].x()) * 1.2 if rr else 120
                    rad = max(40.0, rad)
                    gg = QRadialGradient(QPointF(0, 0), rad)
                    gg.setColorAt(0, QColor(255, 226, 150, 95))
                    gg.setColorAt(1, QColor(255, 226, 150, 0))
                    p.save()
                    p.translate(fl[0])
                    p.scale(1.0, 0.6)
                    p.setPen(Qt.NoPen)
                    p.setBrush(gg)
                    p.drawEllipse(QPointF(0, 0), rad, rad)
                    p.restore()
                if lp:
                    p.setPen(Qt.NoPen)
                    gg = QRadialGradient(lp[0], 34)
                    gg.setColorAt(0, QColor(255, 240, 190, 230))
                    gg.setColorAt(1, QColor(255, 240, 190, 0))
                    p.setBrush(gg)
                    p.drawEllipse(lp[0], 34, 34)

        # power flows hub -> running devices
        hub = model.item("hub")
        if self.show_flows and hub:
            hx, hz = hub["x"] + hub["w"] / 2, hub["z"] + hub["d"] / 2
            for d in model.devices():
                if not d["device"]["on"] or d["id"] not in self._anchors:
                    continue
                ax, ay, az = self._anchors[d["id"]]
                path3 = [(hx, 0.03, hz), (hx, 0.03, az), (ax, 0.03, az), (ax, ay, az)]
                pts = [proj(q) for q in path3]
                if any(q is None for q in pts):
                    continue
                path = QPainterPath(pts[0][0])
                for q in pts[1:]:
                    path.lineTo(q[0])
                watts = self.model.device_w(d) or d["device"]["watts"]
                col = QColor(255, 181, 71) if watts >= 100 else QColor(self.tag_colors["line"])
                glow = QColor(col)
                glow.setAlpha(50)
                p.setBrush(Qt.NoBrush)
                p.setPen(QPen(glow, 6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                p.drawPath(path)
                pen = QPen(col, 2.2, Qt.CustomDashLine, Qt.RoundCap, Qt.RoundJoin)
                pen.setDashPattern([2, 4])
                pen.setDashOffset(-self._phase * 2)
                p.setPen(pen)
                p.drawPath(path)
            hp = self._anchor2d("hub")
            if hp:
                gg = QRadialGradient(hp, 26)
                hub = QColor(self.tag_colors["line"])
                hub.setAlpha(160)
                gg.setColorAt(0, hub)
                hub.setAlpha(0)
                gg.setColorAt(1, hub)
                p.setPen(Qt.NoPen)
                p.setBrush(gg)
                p.drawEllipse(hp, 26, 26)

        # fan blades
        for d in model.devices():
            if d["kind"] == "fan":
                c = self._anchor2d(d["id"])
                if c is None:
                    continue
                ang = self._phase * (18 if d["device"]["on"] else 0)
                p.save()
                p.translate(c)
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(40, 42, 48, 230))
                p.drawEllipse(QPointF(0, 0), 15, 15)
                p.setBrush(QColor(90, 96, 108, 220))
                for i in range(3):
                    p.save()
                    p.rotate(ang + i * 120)
                    p.drawEllipse(QRectF(-4, -14, 8, 14))
                    p.restore()
                p.setBrush(QColor(255, 120, 60) if d["device"]["on"] else QColor(80, 80, 80))
                p.drawEllipse(QPointF(0, 0), 3, 3)
                p.restore()

        # hover outline
        if self._hover:
            hl = QColor(self.tag_colors["line"])
            p.setPen(QPen(hl, 1.6))
            hl.setAlpha(40)
            p.setBrush(hl)
            for poly, iid in self._hit:
                if iid == self._hover:
                    p.drawPolygon(poly)

        # room + device labels
        if self.show_labels:
            f = QFont("Segoe UI")
            f.setPixelSize(12)
            f.setBold(True)
            for room in model.rooms:
                c = proj((room["x"] + room["w"] / 2, 0.02, room["z"] + room["d"] - 0.35))
                if c:
                    load = model.load_w(room["id"])
                    self._tag(p, c[0], f"{room['name'].upper()}   {load:.0f} W",
                              self.tag_colors["room_bg"], self.tag_colors["room_fg"], f, True)
            if self.show_device_labels:
                f.setPixelSize(11)
                f.setBold(False)
                for d in model.devices():
                    a = self._anchor2d(d["id"])
                    if a is None:
                        continue
                    on = d["device"]["on"]
                    if not on and d["id"] != self._hover:
                        p.setPen(QPen(QColor(10, 14, 20, 200), 1.5))
                        p.setBrush(QColor(150, 158, 170))
                        p.drawEllipse(a, 4, 4)
                        continue
                    live = self.model.live_w(d["id"])
                    txt = f"{d['name']}  ·  {live if live is not None else d['device']['watts']:.0f} W" \
                          + ("  live" if live is not None else "")
                    self._tag(p, QPointF(a.x(), a.y() - 16), txt,
                              self.tag_colors["on_bg"] if on else QColor(15, 18, 24, 190),
                              self.tag_colors["on_fg"] if on else QColor(170, 180, 195), f, False,
                              dot=self.tag_colors["on_dot"] if on else QColor(110, 115, 125),
                              bold=d["id"] == self._hover)

    def _tag(self, p, pt, text, bg, fg, font, big, dot=None, bold=False):
        p.setFont(font)
        fm = p.fontMetrics()
        w = fm.horizontalAdvance(text) + (26 if dot else 16)
        h = 24 if big else 20
        r = QRectF(pt.x() - w / 2, pt.y() - h / 2, w, h)
        line = QColor(self.tag_colors["line"])
        line.setAlpha(200 if bold else 70)
        p.setPen(QPen(line, 1.4 if bold else 1))
        p.setBrush(bg)
        p.drawRoundedRect(r, h / 2, h / 2)
        x = r.left() + 8
        if dot:
            p.setPen(Qt.NoPen)
            p.setBrush(dot)
            p.drawEllipse(QPointF(x + 3, r.center().y()), 3.5, 3.5)
            x += 12
        p.setPen(fg)
        p.drawText(QRectF(x, r.top(), w, h), Qt.AlignLeft | Qt.AlignVCenter, text)

    def _tick(self):
        if not self.isVisible():
            return
        animated = any(d["device"]["on"] for d in self.model.devices())
        if animated:
            self._phase += 1.0
            self.update()

    # --------------------------------------------------------------- input --

    def _pick(self, pos):
        for poly, iid in reversed(self._hit):
            if poly.containsPoint(pos, Qt.OddEvenFill):
                return iid
        return ""

    def mousePressEvent(self, e):
        self._drag = (e.position(), e.button(), self.yaw, self.pitch, self.target, False)

    def mouseMoveEvent(self, e):
        if self._drag:
            start, btn, yaw, pitch, target, moved = self._drag
            dx = e.position().x() - start.x()
            dy = e.position().y() - start.y()
            if abs(dx) + abs(dy) > 3:
                self._drag = (start, btn, yaw, pitch, target, True)
                if btn == Qt.LeftButton:
                    self.yaw = yaw - dx * 0.35
                    self.pitch = max(12.0, min(89.0, pitch + dy * 0.3))
                else:
                    _, f, r, u = self._basis()
                    k = self.dist / max(1, self.height()) * 1.2
                    fwd = _norm((f[0], 0, f[2]))
                    self.target = (target[0] - r[0] * dx * k + fwd[0] * dy * k,
                                   target[1],
                                   target[2] - r[2] * dx * k + fwd[2] * dy * k)
                self.invalidate()
            return
        hov = self._pick(e.position())
        if hov != self._hover:
            self._hover = hov
            it = self.model.item(hov) if hov else None
            self.setCursor(Qt.PointingHandCursor if it and it.get("device") else Qt.ArrowCursor)
            if it:
                dev = it.get("device")
                live = self.model.live_w(it["id"])
                self.setToolTip(f"{it['name']} — {live if live is not None else dev['watts']:.0f} W"
                                f"{' (measured)' if live is not None else ''}, {'ON' if dev['on'] else 'off'}"
                                f"  ·  click to switch" if dev else it["name"])
            else:
                self.setToolTip("")
            self.hover_changed.emit(hov)
            self.update()

    def mouseReleaseEvent(self, e):
        if self._drag:
            moved = self._drag[5]
            self._drag = None
            if moved:
                self.invalidate()                 # re-render with smooth textures
            elif e.button() == Qt.LeftButton:
                hit = self._pick(e.position())
                it = self.model.item(hit) if hit else None
                if it and it.get("device"):
                    self.device_clicked.emit(hit)

    def mouseDoubleClickEvent(self, e):
        self.reset_camera()

    def wheelEvent(self, e):
        steps = e.angleDelta().y() / 120.0
        self.dist = max(3.0, min(30.0, self.dist * (0.88 ** steps)))
        self.invalidate()

    def resizeEvent(self, e):
        self._cache = None
        super().resizeEvent(e)
