# SCRAP Screen Recorder Context

## Current State
- Windows desktop recorder built with Python, PyQt6, FFmpeg, MSS, and SoundCard.
- Supports Full Screen and Area recording, desktop or microphone audio, quality presets, and compact controls.
- Hardware encoding is selected when available, with software encoding as fallback.
- Area mode uses an interactive frame and FFmpeg ZMQ crop commands to move or resize the captured region live.
- Known issue: live Area changes still need verification in the user's recording. `record_engine` currently contains duplicate Area filter branches; remove the duplicate and verify that moving the crop changes the recorded pixels.

## TODO
- [ ] Fix the duplicate Area FFmpeg filter and verify live crop movement and resizing in one recording.
- [ ] Confirm the visible Area outline is always outside the captured pixels.
- [ ] Test Full Screen and Area with Desktop Audio and microphone input on the target laptop.
- [ ] Limit Free recordings to 3 minutes.
- [ ] Offer unlimited recording with a one-time Premium purchase.
- [ ] Allow Premium users to record multiple selected areas simultaneously.
- [ ] Package the current app for sale: create a Windows executable and installer, bundle required assets and dependencies, and test installation on a clean machine.
- [ ] Prepare release requirements for selling: versioning, license and purchase flow, code signing, and third-party dependency/FFmpeg notices.
