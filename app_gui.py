import sys
import os
import time
import threading
import subprocess
import ctypes
from pathlib import Path
import numpy as np
import cv2
import mss
import pywinctl
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QComboBox,
    QLabel,
    QListWidget,
    QMessageBox,
)
from PyQt6.QtGui import QIcon, QColor, QPainter, QPen
from PyQt6.QtCore import Qt, QRect

# Register AppUserModelID for taskbar icon handling on Windows
try:
    myappid = "app.scrap.screenrecorder.1.0"
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
except Exception:
    pass

VIDEO_DIR = Path.home() / "Videos" / "ScreenRecordings"
VIDEO_DIR.mkdir(parents=True, exist_ok=True)

CURRENT_TIER = "Pro"


class ActiveRecordingBorder(QWidget):
    """Persistent overlay box indicating an active recording area."""

    def __init__(self, region):
        super().__init__()
        self.region = region
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setGeometry(
            region["left"], region["top"], region["width"], region["height"]
        )
        self.show()

    def paintEvent(self, event):
        painter = QPainter(self)
        pen = QPen(QColor(255, 0, 0), 4)  # Red border during active recording
        painter.setPen(pen)
        painter.drawRect(0, 0, self.width() - 1, self.height() - 1)


class ScreenSelectorOverlay(QWidget):
    """Overlay for custom area crop and window boundary targeting."""

    def __init__(self, mode="Area", callback=None):
        super().__init__()
        self.mode = mode
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
        self.detected_windows = []
        self.highlighted_rect = None

        if self.mode == "Window":
            self.setMouseTracking(True)
            self.fetch_window_rects()

    def fetch_window_rects(self):
        """Fetches active application window dimensions."""
        self.detected_windows = []
        current_hwnd = int(self.winId()) if hasattr(self, "winId") else None

        for win in pywinctl.getAllWindows():
            # Exclude current overlay window
            if hasattr(win, "getHandle") and win.getHandle() == current_hwnd:
                continue
            valid_title = bool(win.title.strip()) if win.title else False
            valid_size = win.width > 100 and win.height > 100
            if win.isVisible and valid_title and valid_size:
                self.detected_windows.append(
                    QRect(win.left, win.top, win.width, win.height)
                )

    def mouseMoveEvent(self, event):
        if self.mode == "Area" and self.is_drawing:
            self.end_point = event.pos()
            self.update()
        elif self.mode == "Window":
            pos = event.pos()
            found = None
            for rect in self.detected_windows:
                if rect.contains(pos):
                    found = rect
                    break
            if found != self.highlighted_rect:
                self.highlighted_rect = found
                self.update()

    def mousePressEvent(self, event):
        if self.mode == "Area":
            self.start_point = event.pos()
            self.end_point = event.pos()
            self.is_drawing = True
            self.update()
        elif self.mode == "Window" and self.highlighted_rect:
            rect = self.highlighted_rect
            region = {
                "top": rect.top(),
                "left": rect.left(),
                "width": rect.width(),
                "height": rect.height(),
            }
            self.close()
            if self.callback:
                self.callback(region)

    def mouseReleaseEvent(self, event):
        if self.mode == "Area" and self.is_drawing:
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

        if self.mode == "Area" and self.start_point and self.end_point:
            rect = QRect(self.start_point, self.end_point).normalized()
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            painter.fillRect(rect, QColor(0, 0, 0, 0))
            painter.setCompositionMode(
                QPainter.CompositionMode.CompositionMode_SourceOver
            )
            painter.setPen(QPen(QColor(212, 175, 55), 2))
            painter.drawRect(rect)

        elif self.mode == "Window" and self.highlighted_rect:
            rect = self.highlighted_rect
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            painter.fillRect(rect, QColor(0, 0, 0, 0))
            painter.setCompositionMode(
                QPainter.CompositionMode.CompositionMode_SourceOver
            )
            painter.setPen(QPen(QColor(212, 175, 55), 3))
            painter.drawRect(rect)


class ScreenRecorderApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SCRAP - Screen Capture & Recording Platform")
        self.setFixedSize(560, 230)

        icon_path = Path("assets") / "icon.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self.is_recording = False
        self.selected_mode = "Full Screen"
        self.area_region = None
        self.active_border = None

        self.init_ui()
        self.apply_styles()

    def init_ui(self):
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(18, 18, 18, 18)

        left_layout = QVBoxLayout()
        left_layout.setSpacing(12)

        mode_layout = QHBoxLayout()
        self.btn_full = QPushButton("Full Screen")
        self.btn_area = QPushButton("Area")
        self.btn_window = QPushButton("Window")

        for btn in (self.btn_full, self.btn_area, self.btn_window):
            btn.setCheckable(True)

        self.btn_full.setChecked(True)
        self.btn_full.clicked.connect(lambda: self.set_mode("Full Screen"))
        self.btn_area.clicked.connect(lambda: self.set_mode("Area"))
        self.btn_window.clicked.connect(lambda: self.set_mode("Window"))

        mode_layout.addWidget(self.btn_full)
        mode_layout.addWidget(self.btn_area)
        mode_layout.addWidget(self.btn_window)
        left_layout.addLayout(mode_layout)

        quality_layout = QHBoxLayout()
        self.lbl_quality = QLabel("Quality:")
        self.combo_quality = QComboBox()

        if CURRENT_TIER == "Pro":
            self.combo_quality.addItems(
                [
                    "Native / Original",
                    "1440p (2K) · 60 FPS",
                    "1080p · 60 FPS",
                    "1080p · 30 FPS",
                    "720p · 30 FPS",
                ]
            )
        else:
            self.combo_quality.addItems(
                [
                    "720p · 30 FPS",
                    "1080p · 30 FPS",
                    "1080p · 60 FPS (Pro)",
                    "1440p (2K) · 60 FPS (Pro)",
                ]
            )

        quality_layout.addWidget(self.lbl_quality)
        quality_layout.addWidget(self.combo_quality)
        left_layout.addLayout(quality_layout)

        self.btn_gallery = QPushButton("📂 View Saved Recordings")
        self.btn_gallery.clicked.connect(self.open_gallery)
        left_layout.addWidget(self.btn_gallery)

        main_layout.addLayout(left_layout, stretch=3)

        right_layout = QVBoxLayout()
        self.btn_record = QPushButton("🔴\nRecord")
        self.btn_record.setObjectName("RecordButton")
        self.btn_record.setFixedSize(110, 110)
        self.btn_record.clicked.connect(self.toggle_recording)

        right_layout.addWidget(self.btn_record, alignment=Qt.AlignmentFlag.AlignCenter)
        main_layout.addLayout(right_layout, stretch=1)

    def apply_styles(self):
        self.setStyleSheet("""
            QMainWindow { background-color: #1c1a19; }
            QLabel { color: #e2d9d5; font-weight: 600; font-size: 13px; }
            QPushButton {
                background-color: #2b2725;
                border: 1px solid #423c39;
                border-radius: 6px;
                padding: 8px 12px;
                font-weight: 600;
                color: #d2c7c1;
            }
            QPushButton:hover {
                background-color: #383330;
                border-color: #635752;
            }
            QPushButton:checked {
                background-color: #3e2e21;
                border: 1px solid #d4af37;
                color: #d4af37;
            }
            QPushButton#RecordButton {
                border-radius: 55px;
                background-color: #282423;
                border: 3px solid #524743;
                color: #ff5252;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton#RecordButton:hover {
                border-color: #ff5252;
                background-color: #332726;
            }
            QComboBox {
                border: 1px solid #423c39;
                border-radius: 6px;
                padding: 6px;
                background-color: #2b2725;
                color: #ffffff;
                font-size: 13px;
            }
            QComboBox QAbstractItemView {
                background-color: #2b2725;
                color: #ffffff;
                selection-background-color: #3e2e21;
                selection-color: #d4af37;
            }
        """)

    def set_mode(self, mode):
        if CURRENT_TIER == "Free" and mode in ["Area", "Window"]:
            msg = f"{mode} capture is a Pro feature.\nPlease upgrade SCRAP."
            QMessageBox.warning(self, "SCRAP Pro Feature", msg)
            self.btn_full.setChecked(True)
            self.btn_area.setChecked(False)
            self.btn_window.setChecked(False)
            return

        self.selected_mode = mode
        self.btn_full.setChecked(mode == "Full Screen")
        self.btn_area.setChecked(mode == "Area")
        self.btn_window.setChecked(mode == "Window")

        if mode in ["Area", "Window"]:
            self.hide()
            self.overlay = ScreenSelectorOverlay(
                mode=mode, callback=self.on_area_selected
            )

    def on_area_selected(self, region):
        self.area_region = region
        self.show()

    def toggle_recording(self):
        if not self.is_recording:
            self.start_recording()
        else:
            self.stop_recording()

    def start_recording(self):
        selected_q = self.combo_quality.currentText()
        if CURRENT_TIER == "Free" and "(Pro)" in selected_q:
            msg = "High resolution/FPS recording requires SCRAP Pro."
            QMessageBox.warning(self, "SCRAP Pro Feature", msg)
            return

        self.is_recording = True
        self.btn_record.setText("⏹\nStop")
        self.btn_record.setStyleSheet(
            "border-radius: 55px; background-color: #d32f2f;"
            "border: 3px solid #ff5252; color: #ffffff;"
            "font-size: 13px; font-weight: bold;"
        )

        # Show persistent boundary for selected Region / Window
        if self.selected_mode in ["Area", "Window"] and self.area_region:
            self.active_border = ActiveRecordingBorder(self.area_region)

        fps = 60.0 if "60 FPS" in selected_q else 30.0
        timestamp = int(time.time())
        output_filename = VIDEO_DIR / f"SCRAP_Recording_{timestamp}.mp4"

        self.rec_thread = threading.Thread(
            target=self.record_engine, args=(output_filename, fps)
        )
        self.rec_thread.start()

    def stop_recording(self):
        self.is_recording = False
        if self.active_border:
            self.active_border.close()
            self.active_border = None

        self.btn_record.setText("🔴\nRecord")
        self.apply_styles()
        QMessageBox.information(self, "Saved", f"Recording saved to:\n{VIDEO_DIR}")

    def record_engine(self, output_file, fps):
        temp_avi = str(VIDEO_DIR / f"temp_{int(time.time())}.avi")
        with mss.mss() as sct:
            valid_mode = self.selected_mode in ["Area", "Window"]
            if valid_mode and self.area_region:
                monitor = self.area_region
            else:
                monitor = sct.monitors[1]

            width, height = monitor["width"], monitor["height"]
            # Enforce even dimensions required by H.264 video codecs
            width = width if width % 2 == 0 else width - 1
            height = height if height % 2 == 0 else height - 1

            fourcc = cv2.VideoWriter_fourcc(*"XVID")
            out = cv2.VideoWriter(temp_avi, fourcc, fps, (width, height))

            while self.is_recording:
                t0 = time.time()
                img = np.array(sct.grab(monitor))
                frame = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
                frame = cv2.resize(frame, (width, height))
                out.write(frame)

                delay = max(1.0 / fps - (time.time() - t0), 0)
                time.sleep(delay)

            out.release()

        # Transcode to final MP4 cleanly and remove temporary AVI file
        ffmpeg_cmd = [
            "ffmpeg",
            "-y",
            "-i",
            temp_avi,
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(output_file),
        ]
        res = subprocess.run(
            ffmpeg_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )

        # Fallback if FFmpeg binary is missing: convert AVI to final filename
        if res.returncode != 0 or not output_file.exists():
            final_avi = output_file.with_suffix(".avi")
            if os.path.exists(temp_avi):
                os.rename(temp_avi, final_avi)
        else:
            if os.path.exists(temp_avi):
                os.remove(temp_avi)

    def open_gallery(self):
        self.gallery = GalleryWindow()
        self.gallery.show()


class GalleryWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SCRAP - Saved Recordings")
        self.setGeometry(200, 200, 440, 320)

        icon_path = Path("assets") / "icon.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self.setStyleSheet("""
            QWidget { background-color: #1c1a19; color: #ffffff; }
            QListWidget {
                background-color: #2b2725;
                border: 1px solid #423c39;
                border-radius: 6px;
                padding: 6px;
                color: #ffffff;
            }
            QListWidget::item:selected {
                background-color: #3e2e21;
                color: #d4af37;
            }
            QPushButton {
                background-color: #2b2725;
                border: 1px solid #423c39;
                border-radius: 6px;
                padding: 8px 12px;
                font-weight: 600;
                color: #d2c7c1;
            }
            QPushButton:hover {
                background-color: #383330;
                border-color: #635752;
            }
        """)

        layout = QVBoxLayout(self)
        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget)

        btn_layout = QHBoxLayout()
        self.btn_open = QPushButton("Play Video")
        self.btn_delete = QPushButton("Delete Video")

        self.btn_open.clicked.connect(self.play_selected)
        self.btn_delete.clicked.connect(self.delete_selected)

        btn_layout.addWidget(self.btn_open)
        btn_layout.addWidget(self.btn_delete)
        layout.addLayout(btn_layout)

        self.refresh_list()

    def refresh_list(self):
        self.list_widget.clear()
        # Scan for both MP4 and AVI files so no recordings are missed
        for ext in ("*.mp4", "*.avi"):
            for file in VIDEO_DIR.glob(ext):
                if not file.name.startswith("temp_"):
                    self.list_widget.addItem(file.name)

    def play_selected(self):
        item = self.list_widget.currentItem()
        if item:
            file_path = VIDEO_DIR / item.text()
            os.startfile(file_path)

    def delete_selected(self):
        item = self.list_widget.currentItem()
        if item:
            file_path = VIDEO_DIR / item.text()
            if os.path.exists(file_path):
                os.remove(file_path)
                self.refresh_list()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = ScreenRecorderApp()
    window.show()
    sys.exit(app.exec())
