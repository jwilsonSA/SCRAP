# SCRAP Development Roadmap

Items are ordered from easiest to hardest. Complete each section before moving to the next.

## Easy

### Recording controls
- [ ] Add configurable countdown duration.
- [ ] Add global keyboard shortcuts and hotkeys.
- [ ] Add a save-location setting; default to the Windows Videos folder.
- [ ] Add configurable audio volume levels for desktop and microphone sources.
- [ ] Add a first-run prompt that confirms desktop loopback and microphone devices are working.
- [ ] Add recording-duration and file-size estimates before recording.

### Quality and usability
- [ ] Add an encoding quality preset selector: Small, Balanced, and High Quality.
- [ ] Add a configurable video bitrate.
- [ ] Add a configurable FPS preset.
- [ ] Add stable native-resolution and monitor-selection behavior for multi-monitor setups.
- [ ] Add cursor visibility and click highlighting options.
- [ ] Add application-window capture in addition to full-screen and custom-area modes.
- [ ] Add recording status indicators for dropped frames, audio activity, CPU use, and encoder name.

### Gallery and settings
- [ ] Add thumbnails and basic duration/file-size metadata to the gallery.
- [ ] Add rename, delete, favorite, and sort controls for recordings.
- [ ] Add searchable recording history.
- [ ] Persist user settings between app sessions.
- [ ] Add light and dark theme options.
- [ ] Add simple in-app help for audio setup and capture troubleshooting.

### Reliability checks
- [ ] Check available disk space before starting.
- [ ] Warn when the selected audio device becomes unavailable.
- [ ] Test audio and video stop/finalization paths on Windows.
- [ ] Add automatic fallback from hardware encoding to software encoding when the encoder fails.
- [ ] Verify live Area movement and resizing in one recorded session.
- [ ] Verify that the visible Area outline never overlaps captured pixels.

## Medium

### Audio
- [ ] Add independent mute controls for desktop and microphone sources.
- [ ] Add optional noise reduction.
- [ ] Add optional audio normalization.
- [ ] Add configurable channel count and audio sample rate.
- [ ] Report audio-device synchronization drift and automatically resynchronize long recordings.

### Recording workflow
- [ ] Automatically recover interrupted recordings where possible.
- [ ] Add crash recovery metadata for active recordings.
- [ ] Add temporary recording folders with an atomic final-save step.
- [ ] Add a pre-recording device and performance test.
- [ ] Add automatic retry or fallback when FFmpeg capture fails.
- [ ] Add a periodic recording-health monitor that can warn without stopping capture.

### Editing and export
- [ ] Add a basic trim-before-save workflow.
- [ ] Add timeline trimming with start and end handles.
- [ ] Add export presets for MP4, WebM, and GIF.
- [ ] Add an export-quality and resolution selector.
- [ ] Add background post-processing so the UI remains responsive.
- [ ] Add basic annotations: text, shapes, and highlights.
- [ ] Add audio silence detection and optional silence trimming.

### Webcam
- [ ] Add webcam-device discovery and preview.
- [ ] Add picture-in-picture placement and size controls.
- [ ] Allow the webcam to be clipped to a circle or rounded rectangle.

## Hard

### Advanced capture
- [ ] Add simultaneous multi-area capture with separate output streams.
- [ ] Add animated zoom and focus follows.
- [ ] Add window tracking when an application moves between monitors.
- [ ] Add virtual camera or live-stream output.
- [ ] Add a scoped recording scheduler or automation API.

### Advanced editing
- [ ] Add a multi-track timeline.
- [ ] Add zoom, pan, crop, transitions, speed changes, and keyframes.
- [ ] Add automatic chapter or highlight detection.
- [ ] Add automatic transcription and captions.
- [ ] Add subtitle positioning and export support.

### Distribution and updates
- [ ] Add signed Windows installer and portable packaging.
- [ ] Add automatic update checking and installation.
- [ ] Add crash reports with opt-in privacy controls.
- [ ] Add clean-machine installation and upgrade testing.
- [ ] Add FFmpeg and third-party dependency notices.
- [ ] Add installer rollback and uninstall cleanup.

### Licensing
- [ ] Select a purchase and license-management provider.
- [ ] Implement server-backed license validation rather than local secret-based checks.
- [ ] Add secure activation, revocation, offline grace periods, and device limits.
- [ ] Add "Unlock Pro" UI and a persisted activation state.
- [ ] Gate premium features consistently and remove any placeholders such as the current hard-coded tier behavior.
- [ ] Decide which features remain free and document the premium matrix in the final product documentation.

## Testing and Release

- [ ] Add focused tests for quality presets, resolution mapping, device selection, and file naming.
- [ ] Add integration tests for desktop audio, microphone audio, and mixed audio.
- [ ] Add integration tests for Full Screen, Area, and window capture.
- [ ] Add FFmpeg output validation for duration, resolution, frame rate, video stream, and audio stream.
- [ ] Add CI builds for source validation and PyInstaller packaging.
- [ ] Add release checks for antivirus false positives, Windows SmartScreen, startup time, and clean-machine behavior.
