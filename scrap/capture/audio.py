import re
import subprocess
import wave

import numpy as np

from scrap.config import FFMPEG_EXE
from scrap.platform import hidden_subprocess_kwargs


def normalize_audio_device_name(name):
    if not name:
        return ""
    normalized = re.sub(r"[^a-z0-9]+", "", str(name).lower())
    for prefix in ("microphone", "speakers", "headphones", "output", "input"):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix):]
            break
    return normalized or re.sub(r"[^a-z0-9]+", "", str(name).lower())


def find_soundcard_microphone(devices, requested_name=None):
    if not devices:
        return None
    if requested_name:
        exact = [
            device
            for device in devices
            if device.name.strip().lower() == requested_name.strip().lower()
        ]
        if exact:
            return exact[0]
        requested_key = normalize_audio_device_name(requested_name)
        normalized = [
            device
            for device in devices
            if normalize_audio_device_name(device.name) == requested_key
            and requested_key
        ]
        if normalized:
            return normalized[0]
        requested_key = requested_key.casefold()
        partial = [
            device
            for device in devices
            if requested_key
            and (
                requested_key in normalize_audio_device_name(device.name).casefold()
                or normalize_audio_device_name(device.name).casefold()
                in requested_key
            )
        ]
        if partial:
            return partial[0]
    return None


def discover_audio_devices():
    try:
        import soundcard

        devices = []
        seen = set()
        for microphone in soundcard.all_microphones(include_loopback=True):
            if microphone.isloopback:
                continue
            name = str(getattr(microphone, "name", "")).strip()
            key = normalize_audio_device_name(name)
            if name and key and key not in seen:
                seen.add(key)
                devices.append(name)
        if devices:
            return ["No Audio", "Desktop Audio", "Desktop + Microphone", *devices]
    except Exception:
        pass

    try:
        result = subprocess.run(
            [
                FFMPEG_EXE,
                "-hide_banner",
                "-list_devices",
                "true",
                "-f",
                "dshow",
                "-i",
                "dummy",
            ],
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


def capture_audio_source(
    output_file,
    stop_event,
    ready_event,
    audio_source,
    pause_event,
    error_callback=None,
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
                for name in (default_speaker.name, getattr(default_speaker, "name", ""))
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
            microphone = find_soundcard_microphone(input_devices, audio_source)
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
            microphones = [
                device
                for device in soundcard.all_microphones(include_loopback=True)
                if not device.isloopback
            ]
            if not loopback_devices:
                raise RuntimeError("No desktop audio loopback device is available.")
            if not microphones:
                raise RuntimeError("No microphone input device is available.")
            try:
                microphone = soundcard.default_microphone()
            except Exception:
                microphone = None
            if microphone is None:
                microphone = microphones[0]
            else:
                microphone = (
                    find_soundcard_microphone(microphones, microphone.name)
                    or microphones[0]
                )
            default_speaker = soundcard.default_speaker()
            expected_names = {
                name.strip().lower()
                for name in (default_speaker.name, getattr(default_speaker, "name", ""))
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
                        microphone_samples = microphone_recorder.record(numframes=4800)
                        desktop_mono = np.mean(
                            np.asarray(desktop_samples, dtype=np.float32),
                            axis=-1 if np.asarray(desktop_samples).ndim > 1 else 0,
                        )
                        microphone_mono = np.mean(
                            np.asarray(microphone_samples, dtype=np.float32),
                            axis=-1 if np.asarray(microphone_samples).ndim > 1 else 0,
                        )
                        frame_count = min(
                            desktop_mono.shape[0],
                            microphone_mono.shape[0],
                        )
                        mixed = (
                            desktop_mono[:frame_count] * 0.65
                            + microphone_mono[:frame_count] * 0.85
                        )
                        mixed = np.clip(mixed, -1.0, 1.0)
                        pcm_mono = (mixed * 32767).astype(np.int16)
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
        if error_callback:
            error_callback(str(exc))
    finally:
        ready_event.set()
