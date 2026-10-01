import sys
import os
import re
import signal
import time
import threading
import subprocess
import ctypes
import wave
from pathlib import Path

import numpy as np
import mss
import pywinctl
import imageio_ffmpeg
import soundcard
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
from PyQt6.QtGui import QIcon, QColor, QPainter, QPen, QCursor, QFont
from PyQt6.QtCore import Qt, QRect, QTimer

# Register AppUserModelID for taskbar icon handling on Windows
try:
    myappid = "app.scrap.screenrecorder.1.0"
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
except Exception:
    pass

# All recordings should be saved to one canonical location only.
VIDEO_DIR = Path.home() / "Videos" / "ScreenRecordings"
VIDEO_DIR.mkdir(parents=True, exist_ok=True)

CURRENT_TIER = "Pro"

# Automatically resolve the bundled ffmpeg executable path
FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()


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
        self.is_locked = False  # Track if a window selection has been locked
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
        """Fetches active application window dimensions cleanly."""
        self.detected_windows = []
        current_hwnd = int(self.winId()) if hasattr(self, "winId") else 0

        for win in pywinctl.getAllWindows():
            try:
                # Exclude current overlay window
                if hasattr(win, "getHandle") and win.getHandle() == current_hwnd:
                    continue

                title = win.title.strip() if win.title else ""
                if not title or not win.isVisible:
                    continue

                w, h = win.width, win.height
                if w > 100 and h > 100:
                    self.detected_windows.append(QRect(win.left, win.top, w, h))
            except Exception:
                # Ignore windows that close, lack permissions, or throw handle errors
                continue

    def mouseMoveEvent(self, event):
        pos = event.pos()
        global_pos = QCursor.pos()

        # Stop moving/tracking once locked
        if self.is_locked:
            return

        if self.mode == "Area" and self.is_drawing:
            self.end_point = pos
            self.update()
        elif self.mode == "Window":
            found = None
            for rect in self.detected_windows:
                if rect.contains(global_pos):
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
            self.is_locked = True
            rect = self.highlighted_rect
            region = {
                "top": rect.top(),
                "left": rect.left(),
                "width": rect.width(),
                "height": rect.height(),
            }
            if self.callback:
                self.callback(region)
            self.close()

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
        self.setFont(QFont("Segoe UI", 10))

        icon_path = Path("assets") / "icon.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self.is_recording = False
        self.selected_mode = "Full Screen"
        self.area_region = None
        self.active_border = None
        self.record_start_time = None
        self.ffmpeg_process = None
        self.ffmpeg_returncode = None
        self.desktop_audio_stop = None
        self.desktop_audio_thread = None
        self.desktop_audio_error = None
        self.desktop_audio_path = None
        self.current_output_file = None
        self.active_audio_source = "No Audio"
        self.record_timer = QTimer(self)
        self.record_timer.setInterval(100)
        self.record_timer.timeout.connect(self.update_record_timer)

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

        right_layout.addWidget(self.lbl_timer, alignment=Qt.AlignmentFlag.AlignCenter)
        right_layout.addWidget(self.lbl_status, alignment=Qt.AlignmentFlag.AlignCenter)
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
        self.selected_mode = mode

        # Uncheck/check mode button visuals
        self.btn_full.setChecked(mode == "Full Screen")
        self.btn_area.setChecked(mode == "Area")

        if mode == "Full Screen":
            self.area_region = None

        # Launch overlay immediately when Area is selected
        if mode == "Area":
            self.overlay = ScreenSelectorOverlay(
                mode=mode, callback=self.on_area_selected
            )
            self.overlay.show()
        else:
            if hasattr(self, "overlay") and self.overlay:
                self.overlay.close()

    def on_area_selected(self, region):
        self.area_region = region
        self.show()

    def toggle_recording(self):
        if not self.is_recording:
            self.start_recording()
        else:
            self.stop_recording()

    def update_record_timer(self):
        if self.record_start_time is None:
            return

        elapsed = time.monotonic() - self.record_start_time
        total_ms = int(elapsed * 1000)
        days, remainder = divmod(total_ms, 86400000)
        hours, remainder = divmod(remainder, 3600000)
        minutes, remainder = divmod(remainder, 60000)
        seconds, milliseconds = divmod(remainder, 1000)

        text = f"{days:02d}:{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"
        self.lbl_timer.setText(text)

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
            return ["No Audio", "Desktop Audio", *devices]
        except Exception:
            pass
        return ["No Audio", "Desktop Audio"]

    def start_recording(self):
        selected_q = self.combo_quality.currentText()
        if CURRENT_TIER == "Free" and "(Pro)" in selected_q:
            msg = "High resolution/FPS recording requires SCRAP Pro."
            QMessageBox.warning(self, "SCRAP Pro Feature", msg)
            return

        if self.selected_mode == "Area":
            if not hasattr(self, "area_region") or not self.area_region:
                QMessageBox.warning(
                    self, "No Area Selected", "Please select a screen area first."
                )
                return

        selected_audio = self.combo_audio.currentText()
        timestamp = int(time.time())
        output_filename = VIDEO_DIR / f"SCRAP_Recording_{timestamp}.mp4"
        self.current_output_file = output_filename
        self.active_audio_source = selected_audio
        self.ffmpeg_returncode = None

        if selected_audio == "Desktop Audio":
            self.desktop_audio_path = output_filename.with_suffix(".desktop.wav")
            self.desktop_audio_stop = threading.Event()
            audio_ready = threading.Event()
            self.desktop_audio_error = None
            self.desktop_audio_thread = threading.Thread(
                target=self.capture_desktop_audio,
                args=(self.desktop_audio_path, self.desktop_audio_stop, audio_ready),
            )
            self.desktop_audio_thread.start()
            if not audio_ready.wait(timeout=10) or self.desktop_audio_error:
                self.desktop_audio_stop.set()
                self.desktop_audio_thread.join(timeout=5)
                error = (
                    self.desktop_audio_error or "Timed out opening the playback device."
                )
                QMessageBox.warning(self, "Desktop Audio Unavailable", error)
                return

        self.is_recording = True
        self.record_start_time = time.monotonic()
        self.lbl_timer.setText("00:00:00:00.000")
        self.lbl_status.setText("Recording...")
        self.record_timer.start()

        self.btn_record.setText("■\nStop")
        self.btn_record.setStyleSheet(
            "border-radius: 55px; background-color: #d32f2f;"
            "border: 3px solid #ff5252; color: #ffffff;"
            "font-size: 13px; font-weight: bold;"
        )

        # Show persistent boundary for selected Area recording
        if self.selected_mode == "Area" and self.area_region:
            self.active_border = ActiveRecordingBorder(self.area_region)

        fps = 60.0 if "60 FPS" in selected_q else 30.0
        target_size = self.resolve_target_size(selected_q)
        self.rec_thread = threading.Thread(
            target=self.record_engine,
            args=(output_filename, fps, target_size, selected_audio),
        )
        self.rec_thread.start()

    def capture_desktop_audio(self, output_file, stop_event, ready_event):
        try:
            loopback_devices = [
                microphone
                for microphone in soundcard.all_microphones(include_loopback=True)
                if microphone.isloopback
            ]
            if not loopback_devices:
                raise RuntimeError("No desktop playback loopback device is available.")

            default_speaker = soundcard.default_speaker()
            microphone = next(
                (
                    device
                    for device in loopback_devices
                    if device.name == default_speaker.name
                ),
                loopback_devices[0],
            )
            channels = min(microphone.channels, 2)

            with wave.open(str(output_file), "wb") as audio_file:
                audio_file.setnchannels(channels)
                audio_file.setsampwidth(2)
                audio_file.setframerate(48000)

                with microphone.recorder(
                    samplerate=48000, channels=list(range(channels))
                ) as recorder:
                    while not stop_event.is_set():
                        samples = recorder.record(numframes=4800)
                        pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16)
                        audio_file.writeframesraw(pcm.tobytes())
                        ready_event.set()
        except Exception as exc:
            self.desktop_audio_error = str(exc)
        finally:
            ready_event.set()

    def stop_recording(self):
        self.is_recording = False
        if self.desktop_audio_stop is not None:
            self.desktop_audio_stop.set()
        self.record_timer.stop()
        self.record_start_time = None
        self.lbl_timer.setText("00:00:00:00.000")
        self.lbl_status.setText("Finalizing video...")

        if self.active_border is not None:
            self.active_border.close()
            self.active_border = None

        self.btn_record.setText("🔴\nRecord")
        self.btn_record.setStyleSheet("")
        self.apply_styles()

        if hasattr(self, "rec_thread") and self.rec_thread.is_alive():
            self.rec_thread.join(timeout=60)

        if self.desktop_audio_thread is not None:
            self.desktop_audio_thread.join(timeout=10)

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
            QMessageBox.warning(
                self,
                "Recording Failed",
                f"FFmpeg exited with code {self.ffmpeg_returncode}.",
            )
            return

        if self.active_audio_source == "Desktop Audio":
            if self.desktop_audio_thread.is_alive() or self.desktop_audio_error:
                self.lbl_status.setText("Desktop audio capture failed")
                QMessageBox.warning(
                    self,
                    "Desktop Audio Failed",
                    self.desktop_audio_error or "Desktop audio capture did not stop.",
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
                    str(self.desktop_audio_path),
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
                    "-movflags",
                    "+faststart",
                    str(muxed_file),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            if mux_result.returncode != 0 or not muxed_file.exists():
                self.lbl_status.setText("Audio mux failed")
                details = (
                    mux_result.stderr[-1200:] or "FFmpeg could not mux desktop audio."
                )
                QMessageBox.warning(self, "Audio Mux Failed", details)
                return

            os.replace(muxed_file, self.current_output_file)
            self.desktop_audio_path.unlink(missing_ok=True)

        if (
            not self.current_output_file.exists()
            or self.current_output_file.stat().st_size == 0
        ):
            self.lbl_status.setText("Recording failed")
            QMessageBox.warning(
                self, "Recording Failed", "FFmpeg did not create a playable recording."
            )
            return

        self.lbl_status.setText("Saved")
        QMessageBox.information(self, "Saved", f"Recording saved to:\n{VIDEO_DIR}")

    def record_engine(self, output_file, fps, target_size=None, audio_device=None):
        monitor = None
        if self.selected_mode == "Area" and self.area_region:
            monitor = self.area_region
        else:
            with mss.MSS() as sct:
                monitor = sct.monitors[1]

        width = monitor["width"] if isinstance(monitor, dict) else 1920
        height = monitor["height"] if isinstance(monitor, dict) else 1080
        left = monitor.get("left", 0) if isinstance(monitor, dict) else 0
        top = monitor.get("top", 0) if isinstance(monitor, dict) else 0

        if target_size is not None:
            width, height = target_size

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

        if audio_device and audio_device not in ("No Audio", "Desktop Audio"):
            ffmpeg_cmd += ["-f", "dshow", "-i", f"audio={audio_device}"]

        ffmpeg_cmd += [
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
        ]

        if audio_device and audio_device not in ("No Audio", "Desktop Audio"):
            ffmpeg_cmd += ["-c:a", "aac", "-movflags", "+faststart"]
        else:
            ffmpeg_cmd += ["-an", "-movflags", "+faststart"]

        ffmpeg_cmd.append(str(output_file))

        creation_flags = 0
        if os.name == "nt":
            creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP

        self.ffmpeg_process = subprocess.Popen(
            ffmpeg_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creation_flags,
        )

        while self.is_recording:
            time.sleep(0.05)

        if self.ffmpeg_process and self.ffmpeg_process.poll() is None:
            try:
                if os.name == "nt":
                    self.ffmpeg_process.send_signal(signal.CTRL_BREAK_EVENT)
                else:
                    self.ffmpeg_process.send_signal(signal.SIGINT)
                self.ffmpeg_process.wait(timeout=25)
            except Exception:
                try:
                    self.ffmpeg_process.terminate()
                    self.ffmpeg_process.wait(timeout=10)
                except Exception:
                    self.ffmpeg_process.kill()
                    self.ffmpeg_process.wait(timeout=10)

                if self.ffmpeg_process:
                    self.ffmpeg_returncode = self.ffmpeg_process.returncode
        self.ffmpeg_process = None

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
    window = ScreenRecorderApp()
    window.show()
    sys.exit(app.exec())
