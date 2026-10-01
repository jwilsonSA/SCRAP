# TODO: Choose Premium Features & License Key Unlocking Plan

## 1. Feature Matrix (Free vs. Pro)

| Feature | Free Tier | Pro / Premium Tier |
| :--- | :--- | :--- |
| **Capture Modes** | Full Screen Only | Full Screen, Custom Region (Area), Specific Window Snapping |
| **Resolution Support** | Up to 720p / 1080p (30 FPS) | 1080p (60 FPS), 1440p (2K), Native Resolution |
| **Frame Rates** | 30 FPS max | 60 FPS |
| **Encoding Acceleration** | Software (`XVID` / `libx264`) | Hardware Accelerated (`h264_nvenc` / `h264_amf`) |
| **Watermark / Ads** | Small watermark on output | Clean output, no watermarks |

---

## 2. Implementation Tasks

- [ ] **License Key Validation Strategy**
  - [ ] Define license key format (e.g., `SCRAP-PRO-XXXX-XXXX-XXXX`)
  - [ ] Implement local cryptographic signature check (HMAC-SHA256)
  - [ ] Set up local config file reader (`%APPDATA%/SCRAP/license.json`)

- [ ] **UI Integration**
  - [ ] Add "Unlock Pro" button to main control panel
  - [ ] Implement license key prompt dialog (`QInputDialog`)
  - [ ] Trigger dynamic UI update upon successful unlock

- [ ] **Feature Gating Logic**
  - [ ] Gate Area and Window capture options for non-Pro users
  - [ ] Gate 1080p 60 FPS and 1440p presets behind Pro check
  - [ ] Show unlock popup when clicking restricted features in Free tier

---

## 3. Architecture Overview
[ User UI Input ] ---> [ Format & Validation ] ---> [ Local Storage ]
|
v
[ App Startup ]   <--- [ Check License File ]  <--- [ Enable Pro Features ]

1. **Format Specification**: License keys follow a structured string format (e.g., `SCRAP-PRO-XXXX-XXXX-XXXX`).
2. **Offline Hash Verification**: Validate key signatures locally using HMAC/SHA-256 with a secret salt to prevent unauthorized generation without needing a live backend server.
3. **Local Token Storage**: Save an encrypted token to `%APPDATA%/SCRAP/license.json` or `~/.config/SCRAP/license.json` upon successful activation.
4. **App State Initialization**: On startup, `app_gui.py` checks for a valid saved token and sets `CURRENT_TIER = "Pro"`.

---

## 4. Activation Code Snippet

```python
import hashlib
import json
from pathlib import Path
from PyQt6.QtWidgets import QInputDialog, QMessageBox, QMainWindow

class ScreenRecorderApp(QMainWindow):
    # ... existing app initializations ...

    def prompt_license_key(self):
        key, ok = QInputDialog.getText(
            self, "Unlock SCRAP Pro", "Enter your SCRAP Pro license key:"
        )
        if ok and key:
            if self.verify_license_key(key.strip()):
                self.save_license(key.strip())
                global CURRENT_TIER
                CURRENT_TIER = "Pro"
                QMessageBox.information(
                    self,
                    "Success",
                    "SCRAP Pro unlocked successfully! Please restart the app to enable all features."
                )
            else:
                QMessageBox.warning(
                    self,
                    "Invalid Key",
                    "The license key entered is invalid. Please check and try again."
                )

    def verify_license_key(self, key: str) -> bool:
        if not key.startswith("SCRAP-PRO-"):
            return False
        secret_salt = "SCRAP_SECRET_2026"
        expected_hash = hashlib.sha256((key[:10] + secret_salt).encode()).hexdigest()[:8].upper()
        return key.endswith(expected_hash)

    def save_license(self, key: str):
        config_dir = Path.home() / ".config" / "SCRAP"
        config_dir.mkdir(parents=True, exist_ok=True)
        license_file = config_dir / "license.json"
        with open(license_file, "w") as f:
            json.dump({"tier": "Pro", "key": key}, f)
