import sys
import os
import time
import threading
import subprocess
import ctypes
import tempfile
from pathlib import Path

import mss
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
    QMessageBox,
    QStackedWidget,
)
from PyQt6.QtGui import QIcon, QColor, QPainter, QPen, QFont, QPixmap
from PyQt6.QtCore import Qt, QRect, QSize, QTimer, QThread

from scrap.config import CURRENT_TIER, VIDEO_DIR
from scrap.platform import hidden_subprocess_kwargs, resource_path
from scrap.capture.audio import (
    capture_audio_source as capture_audio_worker,
    discover_audio_devices,
)
from scrap.capture.mux import MuxWorker
from scrap.capture.recording import (
    build_capture_command,
    detect_video_encoder as detect_video_encoder_service,
    resolve_target_size as resolve_target_size_service,
)
from scrap.capture.area import AreaCropControlMixin
from scrap.ui.gallery import GalleryWindow
from scrap.ui.overlays import ActiveRecordingBorder, ScreenSelectorOverlay

# Register AppUserModelID for taskbar icon handling on Windows
try:
    myappid = "app.scrap.screenrecorder.1.0"
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
except Exception:
    pass

class ScreenRecorderApp(AreaCropControlMixin, QMainWindow):
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
        self.mux_thread = None
        self.mux_worker = None
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

    def _set_audio_capture_error(self, error):
        self.audio_capture_error = str(error)

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
        return resolve_target_size_service(selected_q)

    def detect_video_encoder(self):
        return detect_video_encoder_service()

    def discover_audio_devices(self):
        return discover_audio_devices()

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
                target=capture_audio_worker,
                args=(
                    self.audio_temp_path,
                    self.audio_capture_stop,
                    audio_ready,
                    selected_audio,
                    self.audio_capture_pause,
                ),
                kwargs={"error_callback": self._set_audio_capture_error},
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

    def _start_audio_mux(self):
        muxed_file = self.current_output_file.with_name(
            f"{self.current_output_file.stem}.muxed.mp4"
        )
        self.mux_thread = QThread(self)
        self.mux_worker = MuxWorker(
            self.current_output_file,
            self.audio_temp_path,
            muxed_file,
        )
        self.mux_worker.moveToThread(self.mux_thread)
        self.mux_thread.started.connect(self.mux_worker.run)
        self.mux_worker.finished.connect(self._handle_mux_finished)
        self.mux_worker.finished.connect(self.mux_thread.quit)
        self.mux_thread.finished.connect(self.mux_worker.deleteLater)
        self.mux_thread.finished.connect(self.mux_thread.deleteLater)
        self.mux_thread.start()

    def _handle_mux_finished(self, success, details):
        if not success:
            self.lbl_status.setText("Audio mux failed")
            self._cleanup_desktop_audio_temp()
            self._restore_idle_controls()
            QMessageBox.warning(self, "Audio Mux Failed", details)
            return
        self._cleanup_desktop_audio_temp()
        self._finish_successful_save()

    def _finish_successful_save(self):
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

            self._start_audio_mux()
            return

        self._finish_successful_save()

    def record_engine(self, output_file, fps, target_size=None, crop_control_port=None):
        ffmpeg_cmd = build_capture_command(
            output_file,
            fps,
            self.video_encoder,
            self.selected_mode,
            self.area_region,
            target_size,
            crop_control_port,
        )
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
                if process.stdin and not process.stdin.closed:
                    process.stdin.close()
        if process:
            self.ffmpeg_returncode = ctypes.c_int32(process.returncode).value
        stderr_log.seek(0)
        self.ffmpeg_error_output = stderr_log.read().decode(
            "utf-8", errors="replace"
        )[-4000:]
        stderr_log.close()
        self.ffmpeg_process = None

    def open_gallery(self):
        self.gallery = GalleryWindow()
        self.gallery.show()


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
