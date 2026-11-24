"""Settings panel for application paths, timeouts, and execution parameters."""
from __future__ import annotations

from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QCheckBox, QSpinBox, QFileDialog, QFrame, QMessageBox
)
from app.config import config
from app.database import db
from app.utils.signals import signals


class SettingsPanel(QWidget):
    """Settings configuration panel with persistence in SQLite."""

    def __init__(self):
        super().__init__()
        self._init_ui()
        self._load_saved_settings()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(20)

        # Header
        header = QVBoxLayout()
        title = QLabel("Application Settings")
        title.setStyleSheet("font-size: 26px; font-weight: bold; color: #f8fafc;")
        subtitle = QLabel("Configure directory paths, browser executables, and generation timeouts.")
        subtitle.setStyleSheet("color: #94a3b8; font-size: 13px;")
        header.addWidget(title)
        header.addWidget(subtitle)
        layout.addLayout(header)

        # Settings Card Frame
        card = QFrame()
        card.setStyleSheet("""
            QFrame {
                background-color: #1e1e2d;
                border: 1px solid #2d2d42;
                border-radius: 8px;
                padding: 20px;
            }
            QLabel {
                color: #cbd5e1;
                font-weight: 500;
                font-size: 13px;
            }
            QLineEdit, QSpinBox {
                background-color: #171723;
                border: 1px solid #334155;
                border-radius: 6px;
                color: #f8fafc;
                padding: 8px;
                font-size: 13px;
            }
        """)
        form_layout = QVBoxLayout(card)
        form_layout.setSpacing(16)

        # Output Directory
        form_layout.addWidget(QLabel("Output Images Directory:"))
        out_row = QHBoxLayout()
        self.edit_output_dir = QLineEdit(str(config.output_images_dir.resolve()))
        out_row.addWidget(self.edit_output_dir)
        btn_browse_out = QPushButton("Browse...")
        btn_browse_out.setStyleSheet("""
            QPushButton {
                background-color: #334155;
                color: #f8fafc;
                border-radius: 6px;
                padding: 8px 14px;
            }
        """)
        btn_browse_out.clicked.connect(self._browse_output_dir)
        out_row.addWidget(btn_browse_out)
        form_layout.addLayout(out_row)

        # Custom Chrome Executable Path
        form_layout.addWidget(QLabel("Custom Chrome Executable Path (Optional - defaults to bundled Chromium):"))
        chrome_row = QHBoxLayout()
        self.edit_chrome_path = QLineEdit(config.browser_executable_path)
        self.edit_chrome_path.setPlaceholderText("e.g. C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe")
        chrome_row.addWidget(self.edit_chrome_path)
        btn_browse_chrome = QPushButton("Browse...")
        btn_browse_chrome.setStyleSheet("""
            QPushButton {
                background-color: #334155;
                color: #f8fafc;
                border-radius: 6px;
                padding: 8px 14px;
            }
        """)
        btn_browse_chrome.clicked.connect(self._browse_chrome_path)
        chrome_row.addWidget(btn_browse_chrome)
        form_layout.addLayout(chrome_row)

        # Generation Timeout
        form_layout.addWidget(QLabel("Generation Timeout (seconds):"))
        self.spin_timeout = QSpinBox()
        self.spin_timeout.setRange(30, 900)
        self.spin_timeout.setValue(config.generation_timeout_seconds)
        form_layout.addWidget(self.spin_timeout)

        # Headless Mode Checkbox
        self.chk_headless = QCheckBox("Run browser in headless mode (Uncheck for manual login & observation)")
        self.chk_headless.setChecked(config.headless)
        self.chk_headless.setStyleSheet("color: #cbd5e1; font-size: 13px; margin-top: 6px;")
        form_layout.addWidget(self.chk_headless)

        layout.addWidget(card)

        # Save Button
        btn_save = QPushButton("Save Settings")
        btn_save.setStyleSheet("""
            QPushButton {
                background-color: #6366f1;
                color: #ffffff;
                font-weight: bold;
                border-radius: 6px;
                padding: 12px 24px;
                font-size: 14px;
            }
            QPushButton:hover { background-color: #4f46e5; }
        """)
        btn_save.clicked.connect(self._save_settings)
        layout.addWidget(btn_save)

        layout.addStretch()

    def _browse_output_dir(self) -> None:
        dir_path = QFileDialog.getExistingDirectory(
            self, "Select Output Directory", self.edit_output_dir.text(),
            options=QFileDialog.Option.DontUseNativeDialog
        )
        if dir_path:
            self.edit_output_dir.setText(dir_path)

    def _browse_chrome_path(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Chrome Executable", "",
            options=QFileDialog.Option.DontUseNativeDialog
        )
        if file_path:
            self.edit_chrome_path.setText(file_path)

    def _load_saved_settings(self) -> None:
        saved_output = db.get_setting("output_dir")
        if saved_output:
            self.edit_output_dir.setText(saved_output)
            config.output_images_dir = Path(saved_output)

        saved_chrome = db.get_setting("chrome_path")
        if saved_chrome:
            self.edit_chrome_path.setText(saved_chrome)
            config.browser_executable_path = saved_chrome

        saved_timeout = db.get_setting("generation_timeout")
        if saved_timeout:
            self.spin_timeout.setValue(int(saved_timeout))
            config.generation_timeout_seconds = int(saved_timeout)

        saved_headless = db.get_setting("headless")
        if saved_headless is not None:
            val = (saved_headless == "1")
            self.chk_headless.setChecked(val)
            config.headless = val

    def _save_settings(self) -> None:
        out_dir = self.edit_output_dir.text().strip()
        chrome_path = self.edit_chrome_path.text().strip()
        timeout = self.spin_timeout.value()
        headless = self.chk_headless.isChecked()

        if out_dir:
            config.output_images_dir = Path(out_dir)
            db.set_setting("output_dir", out_dir)

        config.browser_executable_path = chrome_path
        db.set_setting("chrome_path", chrome_path)

        config.generation_timeout_seconds = timeout
        db.set_setting("generation_timeout", str(timeout))

        config.headless = headless
        db.set_setting("headless", "1" if headless else "0")

        QMessageBox.information(self, "Settings Saved", "Application settings saved successfully.")
        signals.status_message.emit("Settings saved.", 3000)
