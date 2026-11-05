import os
import subprocess

from PyQt6.QtCore import QObject, pyqtSignal

from scrap.config import FFMPEG_EXE
from scrap.platform import hidden_subprocess_kwargs
from scrap.capture.audio import get_audio_capture_stats


class MuxWorker(QObject):
    finished = pyqtSignal(bool, str)

    def __init__(self, video_file, audio_file, muxed_file):
        super().__init__()
        self.video_file = video_file
        self.audio_file = audio_file
        self.muxed_file = muxed_file

    def run(self):
        audio_stats = get_audio_capture_stats(self.audio_file)
        if audio_stats["frame_count"] == 0:
            details = (
                "The temporary audio capture is empty or invalid. "
                "Check the selected desktop/microphone device and try again."
            )
            self.finished.emit(False, details)
            return
        if audio_stats["peak"] == 0:
            self.finished.emit(
                False,
                "The temporary audio capture contains only silence. "
                "Check Windows volume/device settings and the selected audio source.",
            )
            return

        result = subprocess.run(
            [
                FFMPEG_EXE,
                "-y",
                "-i",
                str(self.video_file),
                "-i",
                str(self.audio_file),
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
                str(self.muxed_file),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            **hidden_subprocess_kwargs(),
        )
        if result.returncode == 0 and self.muxed_file.exists():
            audio_probe = subprocess.run(
                [
                    FFMPEG_EXE,
                    "-v",
                    "error",
                    "-i",
                    str(self.muxed_file),
                    "-map",
                    "0:a:0",
                    "-f",
                    "null",
                    "-",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
                **hidden_subprocess_kwargs(),
            )
            if audio_probe.returncode != 0:
                self.muxed_file.unlink(missing_ok=True)
                details = (
                    "FFmpeg created the video without a usable audio stream."
                    + (
                        f"\n\n{audio_probe.stderr[-1200:]}"
                        if audio_probe.stderr
                        else ""
                    )
                )
                self.finished.emit(False, details)
                return
            os.replace(self.muxed_file, self.video_file)
            self.finished.emit(True, "")
        else:
            self.muxed_file.unlink(missing_ok=True)
            details = result.stderr[-1200:] or "FFmpeg could not mux desktop audio."
            self.finished.emit(False, details)
