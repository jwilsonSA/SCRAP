import tempfile
import unittest
from pathlib import Path

from scrap.capture.audio import (
    get_audio_capture_stats,
    normalize_audio_device_name,
)
from scrap.capture.recording import build_capture_command, resolve_target_size
from scrap.platform import resource_path


class RecordingServiceTests(unittest.TestCase):
    def test_resolve_target_size(self):
        self.assertEqual(resolve_target_size("720p · 30 FPS"), (1280, 720))
        self.assertEqual(resolve_target_size("1080p · 60 FPS"), (1920, 1080))
        self.assertEqual(resolve_target_size("1440p (2K) · 60 FPS"), (2560, 1440))
        self.assertIsNone(resolve_target_size("Native / Original"))

    def test_normalize_audio_device_name(self):
        self.assertEqual(normalize_audio_device_name("Microphone (Realtek)"), "realtek")
        self.assertEqual(normalize_audio_device_name("Speakers (USB)"), "usb")
        self.assertEqual(normalize_audio_device_name(""), "")

    def test_empty_audio_capture_stats(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            missing = Path(temp_dir) / "missing.wav"
            stats = get_audio_capture_stats(missing)
            self.assertEqual(stats["frame_count"], 0)
            self.assertEqual(stats["duration"], 0.0)
            self.assertEqual(stats["peak"], 0)

    def test_build_full_screen_command(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "recording.mp4"
            command = build_capture_command(
                output,
                30.0,
                "libx264",
                "Full Screen",
                None,
                (1920, 1080),
            )
            self.assertIn("-framerate", command)
            self.assertIn("30.0", command)
            self.assertIn("-c:v", command)
            self.assertEqual(command[-1], str(output))

    def test_build_area_command(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "recording.mp4"
            command = build_capture_command(
                output,
                60.0,
                "libx264",
                "Area",
                {"left": 100, "top": 100, "width": 640, "height": 360},
                (1280, 720),
                12345,
            )
            filter_index = command.index("-vf") + 1
            video_filter = command[filter_index]
            self.assertIn("zmq=bind_address=", video_filter)
            self.assertIn("crop@area=640:360:100:100", video_filter)
            self.assertIn("scale=1280:720", video_filter)

    def test_resource_path_from_source_tree(self):
        path = resource_path("assets/icon.png")
        expected = Path(__file__).resolve().parent.parent / "assets/icon.png"
        self.assertEqual(path, expected)


if __name__ == "__main__":
    unittest.main()
