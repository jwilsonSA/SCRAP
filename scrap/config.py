import imageio_ffmpeg

from scrap.platform import get_default_video_folder

CURRENT_TIER = "Pro"
VIDEO_DIR = get_default_video_folder() / "ScreenRecordings"
VIDEO_DIR.mkdir(parents=True, exist_ok=True)
FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()
