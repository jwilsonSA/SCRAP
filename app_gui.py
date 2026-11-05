import sys
import os
import re
import socket
import time
import threading
import subprocess
import ctypes
import tempfile
import wave
from pathlib import Path

import numpy as np
import mss
import imageio_ffmpeg
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QSplashScreen,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QComboBox,
    QLabel,
    QListWidget,
    QMessageBox,
    QStackedWidget,
)
from PyQt6.QtGui import QIcon, QColor, QPainter, QPen, QFont, QPixmap, QRegion
from PyQt6.QtCore import Qt, QRect, QSize, QTimer

# Register AppUserModelID for taskbar icon handling on Windows
try:
    myappid = "app.scrap.screenrecorder.1.0"
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
except Exception:
    pass

def get_default_video_folder():
    """Return the user's actual Windows Videos folder, including OneDrive redirects."""
    if os.name == "nt":
        try:
            class GUID(ctypes.Structure):
                _fields_ = [
                    ("Data1", ctypes.c_ulong),
                    ("Data2", ctypes.c_ushort),
                    ("Data3", ctypes.c_ushort),
                    ("Data4", ctypes.c_ubyte * 8),
                ]

            videos_guid = GUID()
            # FOLDERID_Videos: {18989B1D-99B5-455B-841C-AB7C74E4DDFC}
            values = "18989B1D99B5455B841CAB7C74E4DDFC"
            videos_guid.Data1 = int(values[0:8], 16)
            videos_guid.Data2 = int(values[8:12], 16)
            videos_guid.Data3 = int(values[12:16], 16)
            videos_guid.Data4[:] = bytes.fromhex(values[16:])

            path_pointer = ctypes.c_wchar_p()
            result = ctypes.windll.shell32.SHGetKnownFolderPath(
                ctypes.byref(videos_guid), 0, None, ctypes.byref(path_pointer)
            )
            if result == 0 and path_pointer.value:
                videos_folder = Path(path_pointer.value)
                ctypes.windll.ole32.CoTaskMemFree(path_pointer)
                return videos_folder
        except Exception:
            pass

    return Path.home() / "Videos"


# All recordings should be saved to the user's canonical Videos folder only.
VIDEO_DIR = get_default_video_folder() / "ScreenRecordings"
VIDEO_DIR.mkdir(parents=True, exist_ok=True)

CURRENT_TIER = "Pro"

# Automatically resolve the bundled ffmpeg executable path
FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()


def hidden_subprocess_kwargs():
    """Prevent Windows console windows from appearing for FFmpeg helpers."""
    if os.name != "nt":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    return {
        "creationflags": subprocess.CREATE_NO_WINDOW,
        "startupinfo": startupinfo,
    }


def resource_path(relative_path):
    """Resolve bundled resources both from source and from the PyInstaller app."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / relative_path
    return Path(__file__).resolve().parent / relative_path


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


class ScreenRecorderApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.full_window_title = "SCRAP - Screen Capture & Recording Platform"
        self.setWindowTitle(self.full_window_title)
        self.setFixedSize(560, 250)
        self.setFont(QFont("Segoe UI", 10))
        self.video_encoder = self.detect_video_encoder()

        icon_path = resource_path("assets/icon.png")
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self.is_recording = False
        self.selected_mode = "Full Screen"
        self.area_region = None
        self.active_border = None
        self.record_start_time = None
        self.record_pause_started_at = None
        self.record_paused_duration = 0.0
        self.is_paused = False
        self.ffmpeg_process = None
        self.ffmpeg_returncode = None
        self.audio_capture_stop = None
        self.audio_capture_thread = None
        self.audio_capture_error = None
        self.audio_capture_pause = None
        self.audio_temp_path = None
        self.ffmpeg_error_output = ""
        self.current_output_file = None
        self.active_audio_source = "No Audio"
        self.is_compact_mode = False
        self.area_crop_port = None
        self.area_crop_stop = None
        self.area_crop_thread = None
        self.area_crop_update_event = None
        self.area_crop_lock = threading.Lock()
        self.pending_area_region = None
        self.area_crop_error = None
        self.record_timer = QTimer(self)
        self.record_timer.setInterval(100)
        self.record_timer.timeout.connect(self.update_record_timer)
        self.countdown_timer = QTimer(self)
        self.countdown_timer.setInterval(1000)
        self.countdown_timer.timeout.connect(self._update_countdown)
        self.countdown_remaining = 0
        self.is_counting_down = False

        self.init_ui()
        self.apply_styles()

    def init_ui(self):
        self.view_stack = QStackedWidget(self)
        self.main_view = QWidget()
        self.view_stack.addWidget(self.main_view)
        main_view_layout = QVBoxLayout(self.main_view)
        main_view_layout.setContentsMargins(12, 6, 12, 10)
        main_view_layout.setSpacing(2)

        header_layout = QHBoxLayout()
        header_layout.addStretch()
        self.btn_compact = QPushButton()
        self.btn_compact.setObjectName("CompactToggle")
        self.btn_compact.setFixedSize(28, 24)
        self.btn_compact.setIcon(self._make_compact_toggle_icon(False))
        self.btn_compact.setIconSize(QSize(18, 18))
        self.btn_compact.setToolTip("Switch to compact controls")
        self.btn_compact.setAccessibleName("Switch to compact controls")
        self.btn_compact.clicked.connect(self.toggle_compact_mode)
        header_layout.addWidget(self.btn_compact)
        main_view_layout.addLayout(header_layout)

        main_layout = QHBoxLayout()
        main_layout.setContentsMargins(6, 0, 6, 0)

        left_layout = QVBoxLayout()
        left_layout.setSpacing(12)

        mode_layout = QHBoxLayout()
        self.btn_full = QPushButton("Full Screen")
        self.btn_area = QPushButton("Area")

        for btn in (self.btn_full, self.btn_area):
            btn.setCheckable(True)

        self.btn_full.setChecked(True)
        self.btn_full.clicked.connect(lambda: self.set_mode("Full Screen"))
        self.btn_area.clicked.connect(lambda: self.set_mode("Area"))

        mode_layout.addWidget(self.btn_full)
        mode_layout.addWidget(self.btn_area)
        left_layout.addLayout(mode_layout)

        quality_layout = QHBoxLayout()
        quality_layout.setSpacing(8)
        quality_layout.setContentsMargins(0, 0, 0, 0)

        self.lbl_quality = QLabel("Quality:")
        self.lbl_quality.setFixedWidth(62)
        self.combo_quality = QComboBox()
        self.combo_quality.setMinimumWidth(210)

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

        audio_layout = QHBoxLayout()
        audio_layout.setSpacing(8)
        audio_layout.setContentsMargins(0, 0, 0, 0)

        self.lbl_audio = QLabel("Audio:")
        self.lbl_audio.setFixedWidth(62)
        self.combo_audio = QComboBox()
        self.combo_audio.setMinimumWidth(210)
        self.combo_audio.addItems(self.discover_audio_devices())

        audio_layout.addWidget(self.lbl_audio)
        audio_layout.addWidget(self.combo_audio)
        left_layout.addLayout(audio_layout)

        self.btn_gallery = QPushButton("📂 View Saved Recordings")
        self.btn_gallery.clicked.connect(self.open_gallery)
        left_layout.addWidget(self.btn_gallery)

        main_layout.addLayout(left_layout, stretch=3)

        right_layout = QVBoxLayout()
        self.lbl_timer = QLabel("00:00:00:00.000")
        self.lbl_timer.setObjectName("RecordingTimer")
        self.lbl_timer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_timer.setVisible(True)

        self.lbl_status = QLabel("Ready")
        self.lbl_status.setObjectName("StatusLabel")
        self.lbl_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_status.setStyleSheet(
            "color: #d7d0cc; font-size: 10px; font-weight: 600;"
        )

        self.btn_record = QPushButton("🔴\nRecord")
        self.btn_record.setObjectName("RecordButton")
        self.btn_record.setFixedSize(110, 110)
        self.btn_record.clicked.connect(self.toggle_recording)
        self.btn_pause = QPushButton("Ⅱ\nPause")
        self.btn_pause.setObjectName("PauseButton")
        self.btn_pause.setFixedSize(110, 110)
        self.btn_pause.clicked.connect(self.toggle_pause_recording)
        self.btn_pause.setEnabled(False)

        right_layout.addWidget(self.lbl_timer, alignment=Qt.AlignmentFlag.AlignCenter)
        right_layout.addWidget(self.lbl_status, alignment=Qt.AlignmentFlag.AlignCenter)
        record_buttons_layout = QHBoxLayout()
        record_buttons_layout.setSpacing(8)
        record_buttons_layout.addWidget(self.btn_record)
        record_buttons_layout.addWidget(self.btn_pause)
        right_layout.addLayout(record_buttons_layout)
        main_layout.addLayout(right_layout, stretch=1)
        main_view_layout.addLayout(main_layout, stretch=1)

        self.compact_view = QWidget()
        compact_layout = QHBoxLayout(self.compact_view)
        compact_layout.setContentsMargins(10, 4, 10, 4)
        compact_layout.setSpacing(8)

        self.compact_status = QLabel("Ready")
        self.compact_status.setObjectName("CompactStatus")
        self.compact_timer = QLabel(self.lbl_timer.text())
        self.compact_timer.setObjectName("CompactTimer")
        self.compact_timer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.compact_timer.setFixedWidth(150)
        self.btn_compact_record = QPushButton()
        self.btn_compact_record.setObjectName("CompactRecordButton")
        self.btn_compact_record.setFixedSize(34, 34)
        self.btn_compact_record.setIcon(self._make_record_icon(False))
        self.btn_compact_record.setIconSize(QSize(16, 16))
        self.btn_compact_record.setToolTip("Start recording")
        self.btn_compact_record.setAccessibleName("Start recording")
        self.btn_compact_record.clicked.connect(self.toggle_recording)
        self.btn_compact_pause = QPushButton("Ⅱ")
        self.btn_compact_pause.setObjectName("CompactPauseButton")
        self.btn_compact_pause.setFixedSize(34, 34)
        self.btn_compact_pause.setToolTip("Pause recording")
        self.btn_compact_pause.setAccessibleName("Pause recording")
        self.btn_compact_pause.clicked.connect(self.toggle_pause_recording)
        self.btn_compact_pause.setEnabled(False)
        self.btn_expand = QPushButton()
        self.btn_expand.setObjectName("CompactToggle")
        self.btn_expand.setFixedSize(28, 28)
        self.btn_expand.setIcon(self._make_compact_toggle_icon(True))
        self.btn_expand.setIconSize(QSize(18, 18))
        self.btn_expand.setToolTip("Expand settings")
        self.btn_expand.setAccessibleName("Expand settings")
        self.btn_expand.clicked.connect(self.toggle_compact_mode)

        compact_layout.addWidget(self.compact_status)
        compact_layout.addWidget(self.compact_timer, stretch=1)
        compact_layout.addWidget(self.btn_compact_record)
        compact_layout.addWidget(self.btn_compact_pause)
        compact_layout.addWidget(self.btn_expand)
        self.view_stack.addWidget(self.compact_view)
        self.setCentralWidget(self.view_stack)

        self.countdown_label = QLabel(self.view_stack)
        self.countdown_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.countdown_label.setFixedSize(120, 120)
        self.countdown_label.setStyleSheet(
            "background: transparent; border: none;"
            "color: #ffffff; font-size: 96px; font-weight: bold;"
        )
        self.countdown_label.hide()

    @staticmethod
    def _make_record_icon(recording):
        pixmap = QPixmap(18, 18)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#ff4d4d"))
        if recording:
            painter.drawRect(4, 4, 10, 10)
        else:
            painter.drawEllipse(3, 3, 12, 12)
        painter.end()
        return QIcon(pixmap)

    @staticmethod
    def _make_compact_toggle_icon(expand):
        pixmap = QPixmap(20, 20)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#f4ede8"), 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(QRect(3, 3, 14, 14), 2, 2)
        painter.drawLine(3, 7, 17, 7)
        if expand:
            painter.drawLine(10, 14, 10, 9)
            painter.drawLine(7, 12, 10, 9)
            painter.drawLine(10, 9, 13, 12)
        else:
            painter.drawLine(10, 9, 10, 14)
            painter.drawLine(7, 11, 10, 14)
            painter.drawLine(10, 14, 13, 11)
        painter.end()
        return QIcon(pixmap)

    def toggle_compact_mode(self):
        self.is_compact_mode = not self.is_compact_mode
        if self.is_compact_mode:
            self.view_stack.setCurrentWidget(self.compact_view)
            self.setWindowTitle("SCRAP")
            self.setFixedSize(360, 82)
        else:
            self.view_stack.setCurrentWidget(self.main_view)
            self.setWindowTitle(self.full_window_title)
            self.setFixedSize(560, 250)

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
            QLabel#RecordingTimer {
                color: #ff4d4d;
                font-size: 12px;
                font-weight: bold;
                letter-spacing: 0.5px;
                min-height: 16px;
            }
            QLabel#StatusLabel {
                color: #d7d0cc;
                font-size: 10px;
                font-weight: 600;
                min-height: 14px;
            }
            QLabel#CompactStatus {
                color: #ff5252;
                font-size: 11px;
                font-weight: bold;
            }
            QLabel#CompactTimer {
                color: #ff4d4d;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton#CompactToggle {
                background-color: #3a3432;
                border: 1px solid #817570;
                border-radius: 4px;
                padding: 2px;
            }
            QPushButton#CompactToggle:hover {
                background-color: #514744;
                border-color: #b4a6a0;
            }
            QPushButton#CompactToggle:pressed {
                background-color: #292423;
                border-color: #d4af37;
            }
            QPushButton#CompactRecordButton {
                background-color: #282423;
                border: 2px solid #524743;
                border-radius: 17px;
                padding: 0;
            }
            QPushButton#CompactRecordButton:hover {
                background-color: #332726;
                border-color: #ff5252;
            }
            QComboBox {
                border: 1px solid #423c39;
                border-radius: 6px;
                padding: 6px;
                background-color: #2b2725;
                color: #ffffff;
                font-family: "Segoe UI";
                font-size: 13px;
                font-weight: 600;
            }
            QComboBox QAbstractItemView {
                background-color: #2b2725;
                color: #ffffff;
                selection-background-color: #3e2e21;
                selection-color: #d4af37;
                font-family: "Segoe UI";
                font-size: 13px;
                font-weight: 600;
            }
        """)

    def set_mode(self, mode):
        if self.is_recording:
            return

        if self.active_border is not None:
            self.active_border.close()
            self.active_border = None

        self.selected_mode = mode

        # Uncheck/check mode button visuals
        self.btn_full.setChecked(mode == "Full Screen")
        self.btn_area.setChecked(mode == "Area")

        if mode == "Full Screen":
            self.area_region = None

        # Launch overlay immediately when Area is selected
        if mode == "Area":
            self.overlay = ScreenSelectorOverlay(callback=self.on_area_selected)
            self.overlay.show()
        else:
            if hasattr(self, "overlay") and self.overlay:
                self.overlay.close()

    def _set_recording_controls_enabled(self, enabled):
        for control in (
            self.btn_full,
            self.btn_area,
            self.combo_quality,
            self.combo_audio,
        ):
            control.setEnabled(enabled)

    def _restore_idle_controls(self):
        self._set_recording_controls_enabled(True)
        self.is_paused = False
        self.record_pause_started_at = None
        self.record_paused_duration = 0.0
        self.btn_record.setEnabled(True)
        self.btn_pause.setText("Ⅱ\nPause")
        self.btn_pause.setEnabled(False)
        self.btn_compact_record.setIcon(self._make_record_icon(False))
        self.btn_compact_record.setToolTip("Start recording")
        self.btn_compact_record.setAccessibleName("Start recording")
        self.btn_compact_record.setStyleSheet("")
        self.btn_compact_record.setEnabled(True)
        self.btn_compact_pause.setText("Ⅱ")
        self.btn_compact_pause.setToolTip("Pause recording")
        self.btn_compact_pause.setAccessibleName("Pause recording")
        self.btn_compact_pause.setEnabled(False)
        self.compact_status.setText("Ready")

    def _cleanup_desktop_audio_temp(self):
        if self.audio_temp_path is None:
            return
        if self.audio_capture_thread and self.audio_capture_thread.is_alive():
            return

        try:
            self.audio_temp_path.unlink(missing_ok=True)
        except OSError:
            pass
        self.audio_temp_path = None

    def on_area_selected(self, region):
        with mss.MSS() as sct:
            bounds = dict(sct.monitors[1])
        width = min(region["width"], bounds["width"])
        height = min(region["height"], bounds["height"])
        left = max(
            bounds["left"],
            min(region["left"], bounds["left"] + bounds["width"] - width),
        )
        top = max(
            bounds["top"],
            min(region["top"], bounds["top"] + bounds["height"] - height),
        )
        self.area_region = {
            "left": left,
            "top": top,
            "width": width - width % 2,
            "height": height - height % 2,
        }
        self.active_border = ActiveRecordingBorder(
            self.area_region, bounds, self.on_area_region_changed
        )
        self.active_border.show()
        self.show()

    def on_area_region_changed(self, region):
        self.area_region = dict(region)
        if self.area_crop_update_event is None:
            return
        with self.area_crop_lock:
            self.pending_area_region = dict(region)
        self.area_crop_update_event.set()

    def _start_area_crop_control(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as port_socket:
            port_socket.bind(("127.0.0.1", 0))
            self.area_crop_port = port_socket.getsockname()[1]

        self.area_crop_stop = threading.Event()
        self.area_crop_update_event = threading.Event()
        self.pending_area_region = dict(self.area_region)
        self.area_crop_error = None
        self.area_crop_thread = threading.Thread(
            target=self._area_crop_command_worker,
            args=(self.area_crop_port, self.area_crop_stop),
            daemon=True,
        )
        self.area_crop_thread.start()
        return self.area_crop_port

    def _area_crop_command_worker(self, port, stop_event):
        import zmq

        context = zmq.Context()
        client = None

        def connect_client():
            new_client = context.socket(zmq.REQ)
            new_client.setsockopt(zmq.LINGER, 0)
            new_client.setsockopt(zmq.SNDTIMEO, 200)
            new_client.connect(f"tcp://127.0.0.1:{port}")
            return new_client

        client = connect_client()
        last_region = None
        try:
            while not stop_event.is_set():
                if not self.area_crop_update_event.wait(0.1):
                    continue
                self.area_crop_update_event.clear()
                with self.area_crop_lock:
                    region = dict(self.pending_area_region)
                if region == last_region:
                    continue

                monitor_left = self.area_region_bounds["left"]
                monitor_top = self.area_region_bounds["top"]
                values = {
                    "w": region["width"],
                    "h": region["height"],
                    "x": region["left"] - monitor_left,
                    "y": region["top"] - monitor_top,
                }
                try:
                    for option, value in values.items():
                        client.send_string(f"crop@area {option} {value}")
                        if not client.poll(250):
                            raise zmq.Again()
                        response = client.recv_string()
                        if not response.startswith("0 "):
                            raise RuntimeError(response)
                    last_region = region
                except (zmq.ZMQError, RuntimeError) as exc:
                    self.area_crop_error = str(exc)
                    client.close(0)
                    client = connect_client()
                    with self.area_crop_lock:
                        self.pending_area_region = region
                    self.area_crop_update_event.set()
                    stop_event.wait(0.1)
        finally:
            client.close(0)
            context.term()

    def _stop_area_crop_control(self):
        if self.area_crop_stop is not None:
            self.area_crop_stop.set()
        if self.area_crop_update_event is not None:
            self.area_crop_update_event.set()
        if self.area_crop_thread is not None:
            self.area_crop_thread.join(timeout=2)
        self.area_crop_port = None
        self.area_crop_stop = None
        self.area_crop_thread = None
        self.area_crop_update_event = None

    def toggle_recording(self):
        if self.is_counting_down:
            return
        if not self.is_recording:
            self.start_recording()
        else:
            self.stop_recording()

    def _suspend_ffmpeg_process(self):
        process = self.ffmpeg_process
        if os.name != "nt" or process is None or process.poll() is not None:
            return
        process_handle = ctypes.windll.kernel32.OpenProcess(
            0x0800, False, process.pid
        )
        if process_handle:
            try:
                ctypes.windll.ntdll.NtSuspendProcess(process_handle)
            finally:
                ctypes.windll.kernel32.CloseHandle(process_handle)

    def _resume_ffmpeg_process(self):
        process = self.ffmpeg_process
        if os.name != "nt" or process is None or process.poll() is not None:
            return
        process_handle = ctypes.windll.kernel32.OpenProcess(
            0x0800, False, process.pid
        )
        if process_handle:
            try:
                ctypes.windll.ntdll.NtResumeProcess(process_handle)
            finally:
                ctypes.windll.kernel32.CloseHandle(process_handle)

    def toggle_pause_recording(self):
        if not self.is_recording:
            return

        if not self.is_paused:
            if self.audio_capture_pause is not None:
                self.audio_capture_pause.set()
            self._suspend_ffmpeg_process()
            self.is_paused = True
            self.record_pause_started_at = time.monotonic()
            self.lbl_status.setText("Paused")
            self.compact_status.setText("Paused")
            self.btn_pause.setText("▶\nResume")
            self.btn_compact_pause.setText("▶")
            self.btn_compact_pause.setToolTip("Resume recording")
            self.btn_compact_pause.setAccessibleName("Resume recording")
        else:
            if self.record_pause_started_at is not None:
                self.record_paused_duration += (
                    time.monotonic() - self.record_pause_started_at
                )
            self.record_pause_started_at = None
            if self.audio_capture_pause is not None:
                self.audio_capture_pause.clear()
            self._resume_ffmpeg_process()
            self.is_paused = False
            self.lbl_status.setText("Recording...")
            self.compact_status.setText("REC")
            self.btn_pause.setText("Ⅱ\nPause")
            self.btn_compact_pause.setText("Ⅱ")
            self.btn_compact_pause.setToolTip("Pause recording")
            self.btn_compact_pause.setAccessibleName("Pause recording")

    def update_record_timer(self):
        if self.record_start_time is None:
            return

        elapsed_end = (
            self.record_pause_started_at
            if self.record_pause_started_at is not None
            else time.monotonic()
        )
        elapsed = (
            elapsed_end - self.record_start_time - self.record_paused_duration
        )
        total_ms = int(elapsed * 1000)
        days, remainder = divmod(total_ms, 86400000)
        hours, remainder = divmod(remainder, 3600000)
        minutes, remainder = divmod(remainder, 60000)
        seconds, milliseconds = divmod(remainder, 1000)

        text = f"{days:02d}:{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"
        self.lbl_timer.setText(text)
        self.compact_timer.setText(text)

    def resolve_target_size(self, selected_q):
        if "Native / Original" in selected_q:
            return None
        if "720p" in selected_q:
            return (1280, 720)
        if "1080p" in selected_q:
            return (1920, 1080)
        if "1440p" in selected_q:
            return (2560, 1440)
        return None

    def detect_video_encoder(self):
        hardware_encoders = (
            ("h264_qsv", ["-preset", "4", "-global_quality", "20"]),
            ("h264_mf", ["-rate_control", "3", "-quality", "80"]),
        )
        for encoder, encoder_options in hardware_encoders:
            probe_cmd = [
                FFMPEG_EXE,
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "color=c=black:s=320x240:r=1",
                "-frames:v",
                "1",
                "-c:v",
                encoder,
                *encoder_options,
                "-pix_fmt",
                "yuv420p",
                "-f",
                "null",
                "-",
            ]
            try:
                result = subprocess.run(
                    probe_cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    timeout=8,
                    **hidden_subprocess_kwargs(),
                )
            except (OSError, subprocess.TimeoutExpired):
                continue
            if result.returncode == 0:
                return encoder
        return "libx264"

    def discover_audio_devices(self):
        try:
            ffmpeg_cmd = [
                FFMPEG_EXE,
                "-hide_banner",
                "-list_devices",
                "true",
                "-f",
                "dshow",
                "-i",
                "dummy",
            ]
            result = subprocess.run(
                ffmpeg_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
                **hidden_subprocess_kwargs(),
            )
            devices = []
            seen = set()
            for line in result.stdout.splitlines():
                match = re.search(r'"([^"]+)" \(audio\)', line)
                if match:
                    name = match.group(1)
                    if name and name not in seen:
                        seen.add(name)
                        devices.append(name)
            return ["No Audio", "Desktop Audio", "Desktop + Microphone", *devices]
        except Exception:
            pass
        return ["No Audio", "Desktop Audio", "Desktop + Microphone"]

    def start_recording(self):
        selected_q = self.combo_quality.currentText()
        if CURRENT_TIER == "Free" and "(Pro)" in selected_q:
            msg = "High resolution/FPS recording requires SCRAP Pro."
            QMessageBox.warning(self, "SCRAP Pro Feature", msg)
            return

        if self.selected_mode == "Area":
            if not self.area_region:
                QMessageBox.warning(
                    self, "No Area Selected", "Please select a screen area first."
                )
                return

        self.is_counting_down = True
        self.countdown_remaining = 3
        self._set_recording_controls_enabled(False)
        self.btn_record.setEnabled(False)
        self.btn_compact_record.setEnabled(False)
        self._show_countdown("3")
        self.lbl_status.setText("Starting in 3...")
        self.compact_status.setText("3")
        self.countdown_timer.start()

    def _show_countdown(self, text):
        self.countdown_label.setText(text)
        x = (self.view_stack.width() - self.countdown_label.width()) // 2
        y = (self.view_stack.height() - self.countdown_label.height()) // 2
        self.countdown_label.move(max(0, x), max(0, y))
        self.countdown_label.raise_()
        self.countdown_label.show()

    def _update_countdown(self):
        self.countdown_remaining -= 1
        if self.countdown_remaining > 0:
            text = str(self.countdown_remaining)
            self._show_countdown(text)
            self.lbl_status.setText(f"Starting in {text}...")
            self.compact_status.setText(text)
            return

        self.countdown_timer.stop()
        self.countdown_label.hide()
        self.is_counting_down = False
        self._begin_recording()

    def _begin_recording(self):
        selected_q = self.combo_quality.currentText()
        selected_audio = self.combo_audio.currentText()
        timestamp = int(time.time())
        output_filename = VIDEO_DIR / f"SCRAP_Recording_{timestamp}.mp4"
        self.current_output_file = output_filename
        self.active_audio_source = selected_audio
        self.ffmpeg_returncode = None

        if selected_audio != "No Audio":
            with tempfile.NamedTemporaryFile(
                prefix="scrap_audio_", suffix=".wav", delete=False
            ) as audio_temp:
                self.audio_temp_path = Path(audio_temp.name)
            self.audio_capture_stop = threading.Event()
            self.audio_capture_pause = threading.Event()
            audio_ready = threading.Event()
            self.audio_capture_error = None
            self.audio_capture_thread = threading.Thread(
                target=self.capture_audio_source,
                args=(
                    self.audio_temp_path,
                    self.audio_capture_stop,
                    audio_ready,
                    selected_audio,
                    self.audio_capture_pause,
                ),
            )
            self.audio_capture_thread.start()
            if not audio_ready.wait(timeout=10) or self.audio_capture_error:
                self.audio_capture_stop.set()
                self.audio_capture_thread.join(timeout=5)
                error = (
                    self.audio_capture_error
                    or "Timed out opening the selected audio device."
                )
                self._cleanup_desktop_audio_temp()
                self._restore_idle_controls()
                QMessageBox.warning(self, "Audio Device Unavailable", error)
                return

        crop_control_port = None
        if self.selected_mode == "Area":
            with mss.MSS() as sct:
                self.area_region_bounds = dict(sct.monitors[1])
            crop_control_port = self._start_area_crop_control()

        self.is_recording = True
        self.is_paused = False
        self._set_recording_controls_enabled(False)
        self.btn_record.setEnabled(True)
        self.btn_compact_record.setEnabled(True)
        self.btn_pause.setEnabled(True)
        self.btn_compact_pause.setEnabled(True)
        self.record_start_time = time.monotonic()
        self.record_pause_started_at = None
        self.record_paused_duration = 0.0
        self.is_paused = False
        self.lbl_timer.setText("00:00:00:00.000")
        self.compact_timer.setText("00:00:00:00.000")
        self.lbl_status.setText("Recording...")
        self.compact_status.setText("REC")
        self.record_timer.start()

        self.btn_record.setText("■\nStop")
        self.btn_record.setStyleSheet(
            "border-radius: 55px; background-color: #d32f2f;"
            "border: 3px solid #ff5252; color: #ffffff;"
            "font-size: 13px; font-weight: bold;"
        )
        self.btn_compact_record.setIcon(self._make_record_icon(True))
        self.btn_compact_record.setToolTip("Stop recording")
        self.btn_compact_record.setAccessibleName("Stop recording")
        self.btn_compact_record.setStyleSheet("background-color: #d32f2f;")

        fps = 60.0 if "60 FPS" in selected_q else 30.0
        target_size = self.resolve_target_size(selected_q)
        self.rec_thread = threading.Thread(
            target=self.record_engine,
            args=(output_filename, fps, target_size, crop_control_port),
        )
        self.rec_thread.start()

    def capture_audio_source(
        self, output_file, stop_event, ready_event, audio_source, pause_event
    ):
        try:
            import soundcard

            combined_audio = audio_source == "Desktop + Microphone"
            is_desktop_audio = audio_source == "Desktop Audio"
            input_devices = [
                microphone
                for microphone in soundcard.all_microphones(include_loopback=True)
                if microphone.isloopback == is_desktop_audio
            ]
            if not combined_audio and not input_devices:
                raise RuntimeError("No matching audio input device is available.")

            if combined_audio or is_desktop_audio:
                default_speaker = soundcard.default_speaker()
                expected_names = {
                    name.strip().lower()
                    for name in (
                        default_speaker.name,
                        getattr(default_speaker, "name", ""),
                    )
                    if name
                }
                microphone = next(
                    (
                        device
                        for device in input_devices
                        if device.name.strip().lower() in expected_names
                    ),
                    input_devices[0],
                )
            else:
                microphone = next(
                    (device for device in input_devices if device.name == audio_source),
                    None,
                )
                if microphone is None:
                    raise RuntimeError(
                        f"The selected audio input was not found: {audio_source}"
                    )

            if combined_audio:
                loopback_devices = [
                    device
                    for device in soundcard.all_microphones(include_loopback=True)
                    if device.isloopback
                ]
                if not loopback_devices:
                    raise RuntimeError("No desktop audio loopback device is available.")

                microphones = [
                    device
                    for device in soundcard.all_microphones(include_loopback=True)
                    if not device.isloopback
                ]
                if not microphones:
                    raise RuntimeError("No microphone input device is available.")

                try:
                    microphone = soundcard.default_microphone()
                except Exception:
                    microphone = None
                if microphone is None:
                    microphone = microphones[0]
                else:
                    microphone = next(
                        (
                            device
                            for device in microphones
                            if device.name == microphone.name
                        ),
                        microphones[0],
                    )

                default_speaker = soundcard.default_speaker()
                expected_names = {
                    name.strip().lower()
                    for name in (
                        default_speaker.name,
                        getattr(default_speaker, "name", ""),
                    )
                    if name
                }
                desktop = next(
                    (
                        device
                        for device in loopback_devices
                        if device.name.strip().lower() in expected_names
                    ),
                    loopback_devices[0],
                )
                desktop_channels = max(1, min(desktop.channels, 2))
                microphone_channels = max(1, min(microphone.channels, 2))

                with wave.open(str(output_file), "wb") as audio_file:
                    audio_file.setnchannels(2)
                    audio_file.setsampwidth(2)
                    audio_file.setframerate(48000)

                    with desktop.recorder(
                        samplerate=48000,
                        channels=list(range(desktop_channels)),
                        blocksize=24000,
                    ) as desktop_recorder, microphone.recorder(
                        samplerate=48000,
                        channels=list(range(microphone_channels)),
                        blocksize=24000,
                    ) as microphone_recorder:
                        paused_since_resumed = False
                        while not stop_event.is_set():
                            if pause_event.wait(timeout=0.05):
                                paused_since_resumed = True
                                continue
                            if paused_since_resumed:
                                desktop_recorder.record(numframes=4800)
                                microphone_recorder.record(numframes=4800)
                                paused_since_resumed = False

                            desktop_samples = desktop_recorder.record(numframes=4800)
                            microphone_samples = microphone_recorder.record(
                                numframes=4800
                            )
                            desktop_mono = np.mean(
                                np.asarray(desktop_samples, dtype=np.float32),
                                axis=-1
                                if np.asarray(desktop_samples).ndim > 1
                                else 0,
                            )
                            microphone_mono = np.mean(
                                np.asarray(microphone_samples, dtype=np.float32),
                                axis=-1
                                if np.asarray(microphone_samples).ndim > 1
                                else 0,
                            )
                            frame_count = min(
                                desktop_mono.shape[0], microphone_mono.shape[0]
                            )
                            mixed = (
                                desktop_mono[:frame_count]
                                + microphone_mono[:frame_count]
                            ) * 0.5
                            mixed = np.clip(mixed, -1.0, 1.0)
                            pcm_mono = (
                                mixed * 32767
                            ).astype(np.int16)
                            pcm = np.column_stack((pcm_mono, pcm_mono))
                            audio_file.writeframesraw(pcm.tobytes())
                            ready_event.set()
                return

            channels = min(microphone.channels, 2)

            with wave.open(str(output_file), "wb") as audio_file:
                audio_file.setnchannels(channels)
                audio_file.setsampwidth(2)
                audio_file.setframerate(48000)

                with microphone.recorder(
                    samplerate=48000,
                    channels=list(range(channels)),
                    blocksize=24000,
                ) as recorder:
                    paused_since_resumed = False
                    while not stop_event.is_set():
                        if pause_event.wait(timeout=0.05):
                            paused_since_resumed = True
                            continue
                        if paused_since_resumed:
                            recorder.record(numframes=4800)
                            paused_since_resumed = False
                        samples = recorder.record(numframes=4800)
                        pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16)
                        audio_file.writeframesraw(pcm.tobytes())
                        ready_event.set()
        except Exception as exc:
            self.audio_capture_error = str(exc)
        finally:
            ready_event.set()

    def stop_recording(self):
        if self.active_border is not None:
            self.active_border.close()
            self.active_border = None

        if self.is_paused:
            if self.audio_capture_pause is not None:
                self.audio_capture_pause.clear()
            self._resume_ffmpeg_process()
            self.is_paused = False

        self.is_recording = False
        self._stop_area_crop_control()
        if self.audio_capture_stop is not None:
            self.audio_capture_stop.set()
        self.record_timer.stop()
        self.record_start_time = None
        self.lbl_timer.setText("00:00:00:00.000")
        self.compact_timer.setText("00:00:00:00.000")
        self.lbl_status.setText("Finalizing video...")
        self.compact_status.setText("Saving")

        self.btn_record.setText("🔴\nRecord")
        self.btn_record.setStyleSheet("")
        self.btn_record.setEnabled(False)
        self.btn_pause.setText("Ⅱ\nPause")
        self.btn_pause.setEnabled(False)
        self.btn_compact_record.setIcon(self._make_record_icon(False))
        self.btn_compact_record.setToolTip("Finalizing recording")
        self.btn_compact_record.setEnabled(False)
        self.btn_compact_pause.setText("Ⅱ")
        self.btn_compact_pause.setToolTip("Pause recording")
        self.btn_compact_pause.setAccessibleName("Pause recording")
        self.btn_compact_pause.setEnabled(False)
        self.apply_styles()

        if hasattr(self, "rec_thread") and self.rec_thread.is_alive():
            self.rec_thread.join(timeout=60)

        if self.audio_capture_thread is not None:
            self.audio_capture_thread.join(timeout=10)

        if hasattr(self, "rec_thread") and self.rec_thread.is_alive():
            self.lbl_status.setText("Recording stop timed out")
            QMessageBox.warning(
                self,
                "Recording Incomplete",
                "The recorder did not stop in time. The file may be incomplete.",
            )
            return

        if self.ffmpeg_returncode not in (None, 0):
            self.lbl_status.setText("Recording failed")
            self._cleanup_desktop_audio_temp()
            self._restore_idle_controls()
            details = self.ffmpeg_error_output.strip()
            message = f"FFmpeg exited with code {self.ffmpeg_returncode}."
            if details:
                message += f"\n\n{details[-1400:]}"
            QMessageBox.warning(
                self,
                "Recording Failed",
                message,
            )
            return

        if self.active_audio_source != "No Audio":
            if self.audio_capture_thread.is_alive():
                self.lbl_status.setText("Audio capture stop timed out")
                QMessageBox.warning(
                    self,
                    "Audio Capture Incomplete",
                    "Audio capture did not stop in time. Restart the app before "
                    "recording again.",
                )
                return

            if self.audio_capture_error:
                self.lbl_status.setText("Audio capture failed")
                self._cleanup_desktop_audio_temp()
                self._restore_idle_controls()
                QMessageBox.warning(
                    self,
                    "Audio Capture Failed",
                    self.audio_capture_error,
                )
                return

            muxed_file = self.current_output_file.with_name(
                f"{self.current_output_file.stem}.muxed.mp4"
            )
            mux_result = subprocess.run(
                [
                    FFMPEG_EXE,
                    "-y",
                    "-i",
                    str(self.current_output_file),
                    "-i",
                    str(self.audio_temp_path),
                    "-map",
                    "0:v:0",
                    "-map",
                    "1:a:0",
                    "-c:v",
                    "copy",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "192k",
                    "-af",
                    "aresample=async=1:first_pts=0",
                    "-shortest",
                    "-movflags",
                    "+faststart",
                    str(muxed_file),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
                **hidden_subprocess_kwargs(),
            )
            if mux_result.returncode != 0 or not muxed_file.exists():
                self.lbl_status.setText("Audio mux failed")
                details = (
                    mux_result.stderr[-1200:] or "FFmpeg could not mux desktop audio."
                )
                muxed_file.unlink(missing_ok=True)
                self._cleanup_desktop_audio_temp()
                self._restore_idle_controls()
                QMessageBox.warning(self, "Audio Mux Failed", details)
                return

            os.replace(muxed_file, self.current_output_file)
            self._cleanup_desktop_audio_temp()

        if (
            not self.current_output_file.exists()
            or self.current_output_file.stat().st_size == 0
        ):
            self.lbl_status.setText("Recording failed")
            self._cleanup_desktop_audio_temp()
            self._restore_idle_controls()
            QMessageBox.warning(
                self, "Recording Failed", "FFmpeg did not create a playable recording."
            )
            return

        self.lbl_status.setText("Saved")
        self._restore_idle_controls()
        QMessageBox.information(self, "Saved", f"Recording saved to:\n{VIDEO_DIR}")

    def record_engine(self, output_file, fps, target_size=None, crop_control_port=None):
        with mss.MSS() as sct:
            monitor = dict(sct.monitors[1])

        width = monitor["width"]
        height = monitor["height"]
        left = monitor["left"]
        top = monitor["top"]

        width = width if width % 2 == 0 else width - 1
        height = height if height % 2 == 0 else height - 1

        ffmpeg_cmd = [
            FFMPEG_EXE,
            "-y",
            "-f",
            "gdigrab",
            "-framerate",
            str(fps),
            "-offset_x",
            str(left),
            "-offset_y",
            str(top),
            "-video_size",
            f"{width}x{height}",
            "-i",
            "desktop",
        ]

        if self.selected_mode == "Area" and self.area_region:
            region = dict(self.area_region)
            crop_width = region["width"] - region["width"] % 2
            crop_height = region["height"] - region["height"] % 2
            output_width, output_height = target_size or (crop_width, crop_height)
            crop_x = region["left"] - left
            crop_y = region["top"] - top
            escaped = "\\" * 2
            zmq_address = f"tcp{escaped}://127.0.0.1{escaped}:{crop_control_port}"
            video_filter = (
                f"zmq=bind_address={zmq_address},"
                f"crop@area={crop_width}:{crop_height}:{crop_x}:{crop_y},"
                f"scale={output_width}:{output_height}:"
                "force_original_aspect_ratio=decrease,"
                f"pad={output_width}:{output_height}:(ow-iw)/2:(oh-ih)/2,setsar=1"
            )
            ffmpeg_cmd += [
                "-vf",
                video_filter,
            ]
        elif target_size is not None:
            output_width, output_height = target_size
            ffmpeg_cmd += [
                "-vf",
                f"scale={output_width}:{output_height}:force_original_aspect_ratio=decrease,"
                f"pad={output_width}:{output_height}:(ow-iw)/2:(oh-ih)/2,setsar=1",
            ]

        ffmpeg_cmd += ["-c:v", self.video_encoder]
        if self.video_encoder == "h264_qsv":
            ffmpeg_cmd += ["-preset", "4", "-global_quality", "18"]
        elif self.video_encoder == "h264_mf":
            ffmpeg_cmd += ["-rate_control", "3", "-quality", "88"]
        else:
            ffmpeg_cmd += ["-preset", "veryfast", "-crf", "18"]
        ffmpeg_cmd += ["-pix_fmt", "yuv420p"]

        ffmpeg_cmd += ["-an", "-movflags", "+faststart"]

        ffmpeg_cmd.append(str(output_file))

        stderr_log = tempfile.TemporaryFile()
        self.ffmpeg_process = subprocess.Popen(
            ffmpeg_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=stderr_log,
            **hidden_subprocess_kwargs(),
        )
        if self.is_paused:
            self._suspend_ffmpeg_process()

        while self.is_recording:
            time.sleep(0.05)

        process = self.ffmpeg_process
        if process and process.poll() is None:
            try:
                if process.stdin:
                    process.stdin.write(b"q\n")
                    process.stdin.flush()
                process.wait(timeout=25)
            except Exception:
                try:
                    process.terminate()
                    process.wait(timeout=10)
                except Exception:
                    process.kill()
                    process.wait(timeout=10)

                if process and process.stdin and not process.stdin.closed:
                    process.stdin.close()

        if process:
            self.ffmpeg_returncode = ctypes.c_int32(process.returncode).value
        stderr_log.seek(0)
        self.ffmpeg_error_output = stderr_log.read().decode("utf-8", errors="replace")[
            -4000:
        ]
        stderr_log.close()
        self.ffmpeg_process = None

    def open_gallery(self):
        self.gallery = GalleryWindow()
        self.gallery.show()


class GalleryWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SCRAP - Saved Recordings")
        self.setGeometry(200, 200, 440, 320)

        icon_path = resource_path("assets/icon.png")
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
        VIDEO_DIR.mkdir(parents=True, exist_ok=True)

        # Grab both mp4 and avi files, excluding temporary files
        recordings = [
            f.name
            for f in VIDEO_DIR.glob("*.*")
            if f.suffix.lower() in (".mp4", ".avi") and not f.name.startswith("temp_")
        ]

        for filename in sorted(recordings, reverse=True):
            self.list_widget.addItem(filename)

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

    splash_icon_path = resource_path("assets/splash.png")
    splash = None
    if splash_icon_path.exists():
        splash_pixmap = QPixmap(str(splash_icon_path)).scaled(
            220,
            220,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        splash = QSplashScreen(
            splash_pixmap,
            Qt.WindowType.SplashScreen | Qt.WindowType.FramelessWindowHint,
        )
        splash.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        splash.setWindowIcon(QIcon(str(splash_icon_path)))
        splash.show()
        app.processEvents()

    window = ScreenRecorderApp()
    window.show()
    if splash is not None:
        splash.finish(window)

    if getattr(sys, "frozen", False):
        try:
            import pyi_splash
            pyi_splash.close()
        except (ImportError, AttributeError):
            pass

    sys.exit(app.exec())
