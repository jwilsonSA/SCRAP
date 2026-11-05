from PyQt6.QtCore import Qt, QRect
from PyQt6.QtGui import QColor, QPainter, QPen, QRegion
from PyQt6.QtWidgets import QWidget


class ActiveRecordingBorder(QWidget):
    """Interactive area frame with its visible outline outside the crop."""

    MARGIN = 12
    MIN_SIZE = 64

    def __init__(self, region, bounds, on_change):
        super().__init__()
        self.region = dict(region)
        self.bounds = bounds
        self.on_change = on_change
        self.drag_handle = None
        self.drag_start = None
        self.drag_region = None
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.update_region(region)

    def update_region(self, region):
        self.region = dict(region)
        margin = self.MARGIN
        self.setGeometry(
            self.region["left"] - margin,
            self.region["top"] - margin,
            self.region["width"] + margin * 2,
            self.region["height"] + margin * 2,
        )
        selection = QRect(margin, margin, self.region["width"], self.region["height"])
        self.setMask(QRegion(self.rect()).subtracted(QRegion(selection)))
        self.update()

    def _hit_test(self, pos):
        margin = self.MARGIN
        left = pos.x() < margin
        right = pos.x() >= margin + self.region["width"]
        top = pos.y() < margin
        bottom = pos.y() >= margin + self.region["height"]
        if top and left:
            return "top_left"
        if top and right:
            return "top_right"
        if bottom and left:
            return "bottom_left"
        if bottom and right:
            return "bottom_right"
        if top:
            return "move"
        if bottom:
            return "bottom"
        if left:
            return "left"
        if right:
            return "right"
        return None

    def mousePressEvent(self, event):
        self.drag_handle = self._hit_test(event.position().toPoint())
        self.drag_start = event.globalPosition().toPoint()
        self.drag_region = dict(self.region)
        event.accept()

    def mouseMoveEvent(self, event):
        if self.drag_handle is None:
            handle = self._hit_test(event.position().toPoint())
            if handle == "move":
                cursor = Qt.CursorShape.SizeAllCursor
            elif handle in ("left", "right"):
                cursor = Qt.CursorShape.SizeHorCursor
            elif handle in ("top", "bottom"):
                cursor = Qt.CursorShape.SizeVerCursor
            elif handle in ("top_left", "bottom_right"):
                cursor = Qt.CursorShape.SizeFDiagCursor
            elif handle in ("top_right", "bottom_left"):
                cursor = Qt.CursorShape.SizeBDiagCursor
            else:
                cursor = Qt.CursorShape.ArrowCursor
            self.setCursor(cursor)
            return

        current = event.globalPosition().toPoint()
        delta_x = current.x() - self.drag_start.x()
        delta_y = current.y() - self.drag_start.y()
        original = self.drag_region
        left = original["left"]
        top = original["top"]
        right = left + original["width"]
        bottom = top + original["height"]
        if self.drag_handle == "move":
            left += delta_x
            top += delta_y
            right += delta_x
            bottom += delta_y
        else:
            if "left" in self.drag_handle:
                left = min(left + delta_x, right - self.MIN_SIZE)
            if "right" in self.drag_handle:
                right = max(right + delta_x, left + self.MIN_SIZE)
            if "top" in self.drag_handle:
                top = min(top + delta_y, bottom - self.MIN_SIZE)
            if "bottom" in self.drag_handle:
                bottom = max(bottom + delta_y, top + self.MIN_SIZE)
        bounds_right = self.bounds["left"] + self.bounds["width"]
        bounds_bottom = self.bounds["top"] + self.bounds["height"]
        width = min(right - left, bounds_right - self.bounds["left"])
        height = min(bottom - top, bounds_bottom - self.bounds["top"])
        left = max(self.bounds["left"], min(left, bounds_right - width))
        top = max(self.bounds["top"], min(top, bounds_bottom - height))
        width -= width % 2
        height -= height % 2
        region = {"left": left, "top": top, "width": width, "height": height}
        self.update_region(region)
        self.on_change(region)

    def mouseReleaseEvent(self, event):
        self.drag_handle = None
        self.drag_start = None
        self.drag_region = None
        event.accept()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(255, 54, 68), 3))
        margin = self.MARGIN
        painter.drawRect(
            QRect(
                margin - 2,
                margin - 2,
                self.region["width"] + 3,
                self.region["height"] + 3,
            )
        )


class ScreenSelectorOverlay(QWidget):
    """Overlay for custom area selection."""

    def __init__(self, callback=None):
        super().__init__()
        self.callback = callback
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.showFullScreen()
        self.start_point = None
        self.end_point = None
        self.is_drawing = False

    def mouseMoveEvent(self, event):
        if self.is_drawing:
            self.end_point = event.pos()
            self.update()

    def mousePressEvent(self, event):
        self.start_point = event.pos()
        self.end_point = event.pos()
        self.is_drawing = True
        self.update()

    def mouseReleaseEvent(self, event):
        if self.is_drawing:
            self.is_drawing = False
            rect = QRect(self.start_point, self.end_point).normalized()
            region = {
                "top": rect.top(),
                "left": rect.left(),
                "width": rect.width(),
                "height": rect.height(),
            }
            self.close()
            if self.callback:
                self.callback(region)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 100))
        if self.start_point and self.end_point:
            rect = QRect(self.start_point, self.end_point).normalized()
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            painter.fillRect(rect, QColor(0, 0, 0, 0))
            painter.setCompositionMode(
                QPainter.CompositionMode.CompositionMode_SourceOver
            )
            painter.setPen(QPen(QColor(212, 175, 55), 2))
            painter.drawRect(rect)
