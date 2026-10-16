from typing import List, Optional
from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QLinearGradient, QPolygonF, QFont
from PySide6.QtWidgets import QWidget
from app.config import COLOR_BORDER_MUTED, COLOR_CYAN, COLOR_GREEN, COLOR_PANEL_BG, FONT_FAMILY_MONO

class CyberLineChart(QWidget):
    """High-performance custom painted sci-fi oscilloscope / telemetry graph."""

    def __init__(self, title: str = "TELEMETRY", accent_color: str = COLOR_CYAN,
                 max_points: int = 40, unit: str = "%", parent=None):
        super().__init__(parent)
        self.title = title
        self.accent_hex = accent_color
        self.accent_color = QColor(accent_color)
        self.max_points = max_points
        self.unit = unit
        self.data: List[float] = [0.0] * max_points
        self.current_val = 0.0
        self.setMinimumHeight(110)

    def add_point(self, val: float):
        self.current_val = val
        self.data.append(val)
        if len(self.data) > self.max_points:
            self.data.pop(0)
        self.update()

    def set_data(self, data_list: List[float]):
        self.data = data_list[-self.max_points:]
        if self.data:
            self.current_val = self.data[-1]
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        w = self.width()
        h = self.height()

        # Background
        painter.fillRect(0, 0, w, h, QColor(COLOR_PANEL_BG))

        # Thin Cyber Border
        painter.setPen(QPen(QColor(COLOR_BORDER_MUTED), 1))
        painter.drawRect(0, 0, w - 1, h - 1)

        # Padding for graph plotting
        pad_top = 26
        pad_bottom = 12
        pad_left = 12
        pad_right = 12
        graph_w = w - pad_left - pad_right
        graph_h = h - pad_top - pad_bottom

        # Grid lines (oscilloscope feel)
        grid_pen = QPen(QColor("#0e201d"), 1, Qt.DashLine)
        painter.setPen(grid_pen)
        for i in range(1, 4):
            y = pad_top + int(graph_h * (i / 4.0))
            painter.drawLine(pad_left, y, w - pad_right, y)

        for i in range(1, 6):
            x = pad_left + int(graph_w * (i / 6.0))
            painter.drawLine(x, pad_top, x, h - pad_bottom)

        # Plot line & gradient fill
        if len(self.data) > 1 and graph_h > 0 and graph_w > 0:
            step_x = graph_w / (self.max_points - 1)
            points = []
            max_scale = 100.0 if self.unit == "%" else max(max(self.data), 1.0)

            for i, val in enumerate(self.data):
                clamped_val = min(max(val, 0.0), max_scale)
                ratio = clamped_val / max_scale
                px = pad_left + i * step_x
                py = pad_top + graph_h - (ratio * graph_h)
                points.append(QPointF(px, py))

            # Fill beneath curve
            poly_points = [QPointF(pad_left, pad_top + graph_h)] + points + [QPointF(points[-1].x(), pad_top + graph_h)]
            polygon = QPolygonF(poly_points)

            grad = QLinearGradient(0, pad_top, 0, pad_top + graph_h)
            grad_c1 = QColor(self.accent_color)
            grad_c1.setAlpha(60)
            grad_c2 = QColor(self.accent_color)
            grad_c2.setAlpha(5)
            grad.setColorAt(0, grad_c1)
            grad.setColorAt(1, grad_c2)

            painter.setBrush(QBrush(grad))
            painter.setPen(Qt.NoPen)
            painter.drawPolygon(polygon)

            # Draw the neon trend line
            line_pen = QPen(self.accent_color, 1.8)
            painter.setPen(line_pen)
            for i in range(len(points) - 1):
                painter.drawLine(points[i], points[i + 1])

            # Draw glowing current head point
            head_pt = points[-1]
            painter.setBrush(QBrush(self.accent_color))
            painter.setPen(QPen(QColor("#ffffff"), 1))
            painter.drawEllipse(head_pt, 3.0, 3.0)

        # Draw Header & Value Readout
        font_header = QFont("Consolas", 8, QFont.Bold)
        painter.setFont(font_header)
        painter.setPen(QColor("#789890"))
        painter.drawText(pad_left, 17, self.title.upper())

        # Current Value badge
        val_str = f"{self.current_val:3.1f}{self.unit}" if self.unit == "%" else f"{self.current_val:.1f} {self.unit}"
        painter.setPen(self.accent_color)
        val_rect_w = 90
        painter.drawText(w - pad_right - val_rect_w, 17, val_rect_w, 18, Qt.AlignRight, val_str)
