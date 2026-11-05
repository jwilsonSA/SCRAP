import os
import subprocess

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QListWidget,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from scrap.config import VIDEO_DIR
from scrap.platform import hidden_subprocess_kwargs, resource_path


class GalleryWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SCRAP - Saved Recordings")
        self.setGeometry(200, 200, 440, 320)

        icon_path = resource_path("assets/icon.png")
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
        self.btn_location = QPushButton("Open File Location")
        self.btn_delete = QPushButton("Delete Video")
        self.btn_open.clicked.connect(self.play_selected)
        self.btn_location.clicked.connect(self.open_selected_location)
        self.btn_delete.clicked.connect(self.delete_selected)
        self.list_widget.currentItemChanged.connect(self.update_action_buttons)
        btn_layout.addWidget(self.btn_open)
        btn_layout.addWidget(self.btn_location)
        btn_layout.addWidget(self.btn_delete)
        layout.addLayout(btn_layout)

        self.refresh_list()
        self.update_action_buttons()

    def refresh_list(self):
        self.list_widget.clear()
        VIDEO_DIR.mkdir(parents=True, exist_ok=True)
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
            os.startfile(VIDEO_DIR / item.text())

    def update_action_buttons(self, *_args):
        has_selection = self.list_widget.currentItem() is not None
        self.btn_location.setEnabled(has_selection)
        self.btn_open.setEnabled(has_selection)
        self.btn_delete.setEnabled(has_selection)

    def open_selected_location(self):
        item = self.list_widget.currentItem()
        if not item:
            return
        file_path = (VIDEO_DIR / item.text()).resolve()
        if not file_path.is_file():
            QMessageBox.warning(
                self, "File Not Found", "The selected recording no longer exists."
            )
            self.refresh_list()
            return
        try:
            if os.name == "nt":
                subprocess.Popen(
                    ["explorer.exe", "/select,", str(file_path)],
                    **hidden_subprocess_kwargs(),
                )
            else:
                subprocess.Popen(["xdg-open", str(file_path.parent)])
        except OSError as error:
            QMessageBox.warning(
                self,
                "Unable to Open Location",
                f"Could not open the recording's file location:\n{error}",
            )

    def delete_selected(self):
        item = self.list_widget.currentItem()
        if item:
            file_path = VIDEO_DIR / item.text()
            if os.path.exists(file_path):
                os.remove(file_path)
                self.refresh_list()
