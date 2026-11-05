import os
import subprocess

from PyQt6.QtCore import QObject, pyqtSignal

from scrap.config import FFMPEG_EXE
from scrap.platform import hidden_subprocess_kwargs


class MuxWorker(QObject):
    finished = pyqtSignal(bool, str)

    def __init__(self, video_file, audio_file, muxed_file):
        super().__init__()
        self.video_file = video_file
        self.audio_file = audio_file
        self.muxed_file = muxed_file

    def run(self):
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
            os.replace(self.muxed_file, self.video_file)
            self.finished.emit(True, "")
        else:
            self.muxed_file.unlink(missing_ok=True)
            details = result.stderr[-1200:] or "FFmpeg could not mux desktop audio."
            self.finished.emit(False, details)
