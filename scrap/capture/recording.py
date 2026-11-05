import subprocess

import mss

from scrap.config import FFMPEG_EXE
from scrap.platform import hidden_subprocess_kwargs


def resolve_target_size(selected_quality):
    if "Native / Original" in selected_quality:
        return None
    if "720p" in selected_quality:
        return (1280, 720)
    if "1080p" in selected_quality:
        return (1920, 1080)
    if "1440p" in selected_quality:
        return (2560, 1440)
    return None


def detect_video_encoder():
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


def build_capture_command(
    output_file,
    fps,
    video_encoder,
    selected_mode,
    area_region,
    target_size=None,
    crop_control_port=None,
):
    with mss.MSS() as sct:
        monitor = dict(sct.monitors[1])
    width = monitor["width"]
    height = monitor["height"]
    left = monitor["left"]
    top = monitor["top"]
    width = width if width % 2 == 0 else width - 1
    height = height if height % 2 == 0 else height - 1
    command = [
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
    if selected_mode == "Area" and area_region:
        region = dict(area_region)
        crop_width = region["width"] - region["width"] % 2
        crop_height = region["height"] - region["height"] % 2
        output_width, output_height = target_size or (crop_width, crop_height)
        crop_x = region["left"] - left
        crop_y = region["top"] - top
        escaped = "\\" * 2
        zmq_address = f"tcp{escaped}://127.0.0.1{escaped}:{crop_control_port}"
        command += [
            "-vf",
            (
                f"zmq=bind_address={zmq_address},"
                f"crop@area={crop_width}:{crop_height}:{crop_x}:{crop_y},"
                f"scale={output_width}:{output_height}:"
                "force_original_aspect_ratio=decrease,"
                f"pad={output_width}:{output_height}:(ow-iw)/2:(oh-ih)/2,setsar=1"
            ),
        ]
    elif target_size is not None:
        output_width, output_height = target_size
        command += [
            "-vf",
            (
                f"scale={output_width}:{output_height}:"
                "force_original_aspect_ratio=decrease,"
                f"pad={output_width}:{output_height}:(ow-iw)/2:(oh-ih)/2,setsar=1"
            ),
        ]
    command += ["-c:v", video_encoder]
    if video_encoder == "h264_qsv":
        command += ["-preset", "4", "-global_quality", "18"]
    elif video_encoder == "h264_mf":
        command += ["-rate_control", "3", "-quality", "88"]
    else:
        command += ["-preset", "veryfast", "-crf", "18"]
    command += ["-pix_fmt", "yuv420p", "-an", "-movflags", "+faststart"]
    command.append(str(output_file))
    return command
