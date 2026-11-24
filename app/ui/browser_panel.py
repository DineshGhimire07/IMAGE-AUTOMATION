"""Browser connection panel for managing dedicated Chrome profile and ChatGPT session."""
from __future__ import annotations

import asyncio
from datetime import datetime
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QTextEdit, QMessageBox, QGridLayout
)
from app.config import config
from app.browser.browser_manager import browser_manager
from app.automation.task_manager import task_manager
from app.utils.signals import signals
from app.utils.logger import logger


class BrowserPanel(QWidget):
    """Panel managing dedicated browser profile launch, connection test, and ChatGPT session."""

    def __init__(self):
        super().__init__()
        self._init_ui()
        self._connect_signals()
        self.update_ui_state()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(20)

        # Header
        header = QVBoxLayout()
        title = QLabel("Chrome & ChatGPT Connection")
        title.setStyleSheet("font-size: 26px; font-weight: bold; color: #f8fafc;")
        subtitle = QLabel("Manage your dedicated persistent Chrome browser profile, log in to ChatGPT, and verify connection.")
        subtitle.setStyleSheet("color: #94a3b8; font-size: 13px;")
        header.addWidget(title)
        header.addWidget(subtitle)
        layout.addLayout(header)

        # Status Cards Grid
        grid_frame = QFrame()
        grid_frame.setStyleSheet("""
            QFrame {
                background-color: #1e1e2d;
                border: 1px solid #2d2d42;
                border-radius: 8px;
                padding: 16px;
            }
        """)
        grid = QGridLayout(grid_frame)
        grid.setSpacing(14)

        grid.addWidget(QLabel("Browser Status:"), 0, 0)
        self.val_browser_status = QLabel("Not Running")
        self.val_browser_status.setStyleSheet("color: #ef4444; font-weight: bold; font-size: 14px;")
        grid.addWidget(self.val_browser_status, 0, 1)

        grid.addWidget(QLabel("ChatGPT Accessibility:"), 1, 0)
        self.val_chatgpt_status = QLabel("Disconnected")
        self.val_chatgpt_status.setStyleSheet("color: #94a3b8; font-weight: bold; font-size: 14px;")
        grid.addWidget(self.val_chatgpt_status, 1, 1)

        grid.addWidget(QLabel("Login Status:"), 2, 0)
        self.val_login_status = QLabel("Unknown")
        self.val_login_status.setStyleSheet("color: #94a3b8; font-weight: bold; font-size: 14px;")
        grid.addWidget(self.val_login_status, 2, 1)

        grid.addWidget(QLabel("Current Page URL:"), 3, 0)
        self.val_url = QLabel("N/A")
        self.val_url.setStyleSheet("color: #38bdf8; font-size: 13px;")
        grid.addWidget(self.val_url, 3, 1)

        grid.addWidget(QLabel("Last Connection Check:"), 4, 0)
        self.val_last_check = QLabel("Never")
        self.val_last_check.setStyleSheet("color: #94a3b8; font-size: 13px;")
        grid.addWidget(self.val_last_check, 4, 1)

        grid.addWidget(QLabel("Dedicated Profile Path:"), 5, 0)
        self.val_profile = QLabel(str(config.browser_profile_dir.resolve()))
        self.val_profile.setStyleSheet("color: #64748b; font-size: 12px;")
        grid.addWidget(self.val_profile, 5, 1)

        layout.addWidget(grid_frame)

        # Action Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)

        self.btn_launch = QPushButton("1. Launch Browser")
        self.btn_launch.setStyleSheet("""
            QPushButton {
                background-color: #6366f1;
                color: #ffffff;
                font-weight: bold;
                border-radius: 6px;
                padding: 10px 20px;
                font-size: 14px;
            }
            QPushButton:hover { background-color: #4f46e5; }
        """)
        self.btn_launch.clicked.connect(self._launch_browser)
        btn_layout.addWidget(self.btn_launch)

        self.btn_connect = QPushButton("2. Open ChatGPT")
        self.btn_connect.setStyleSheet("""
            QPushButton {
                background-color: #3b82f6;
                color: #ffffff;
                font-weight: bold;
                border-radius: 6px;
                padding: 10px 18px;
                font-size: 14px;
            }
            QPushButton:hover { background-color: #2563eb; }
        """)
        self.btn_connect.clicked.connect(self._navigate_chatgpt)
        btn_layout.addWidget(self.btn_connect)

        self.btn_test = QPushButton("Test Connection & Readiness")
        self.btn_test.setStyleSheet("""
            QPushButton {
                background-color: #334155;
                color: #f1f5f9;
                border-radius: 6px;
                padding: 10px 18px;
                font-size: 13px;
            }
            QPushButton:hover { background-color: #475569; }
        """)
        self.btn_test.clicked.connect(self._test_connection)
        btn_layout.addWidget(self.btn_test)

        self.btn_disconnect = QPushButton("Close Browser")
        self.btn_disconnect.setStyleSheet("""
            QPushButton {
                background-color: #dc2626;
                color: #ffffff;
                border-radius: 6px;
                padding: 10px 18px;
                font-size: 13px;
            }
            QPushButton:hover { background-color: #b91c1c; }
        """)
        self.btn_disconnect.clicked.connect(self._close_browser)
        btn_layout.addWidget(self.btn_disconnect)

        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        # Instructions Banner
        instructions = QFrame()
        instructions.setStyleSheet("""
            QFrame {
                background-color: #171723;
                border-left: 4px solid #6366f1;
                border-radius: 6px;
                padding: 12px;
            }
        """)
        inst_layout = QVBoxLayout(instructions)
        inst_lbl = QLabel(
            "Workflow Instructions:\n"
            "1. Click 'Launch Browser' to open the dedicated profile window.\n"
            "2. Click 'Open ChatGPT' and log in with your ChatGPT account manually.\n"
            "   (Your session cookies remain saved securely in the dedicated profile across restarts).\n"
            "3. Click 'Test Connection & Readiness' to verify the conversation composer is active and ready."
        )
        inst_lbl.setStyleSheet("color: #cbd5e1; font-size: 13px; line-height: 1.4;")
        inst_layout.addWidget(inst_lbl)
        layout.addWidget(instructions)

        # Diagnostics Log Box
        layout.addWidget(QLabel("Connection Diagnostics Log:"))
        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setStyleSheet("""
            QTextEdit {
                background-color: #0f172a;
                border: 1px solid #1e293b;
                border-radius: 6px;
                color: #38bdf8;
                font-family: monospace;
                font-size: 12px;
                padding: 8px;
            }
        """)
        layout.addWidget(self.log_box)

    def _connect_signals(self) -> None:
        signals.browser_log.connect(self._append_log)

    def _append_log(self, text: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_box.append(f"[{timestamp}] {text}")

    def update_ui_state(self) -> None:
        is_running = browser_manager.is_running
        if is_running:
            self.val_browser_status.setText("Running")
            self.val_browser_status.setStyleSheet("color: #34d399; font-weight: bold; font-size: 14px;")
            self.btn_launch.setEnabled(False)
            self.btn_connect.setEnabled(True)
            self.btn_disconnect.setEnabled(True)
            self.btn_test.setEnabled(True)
        else:
            self.val_browser_status.setText("Not Running")
            self.val_browser_status.setStyleSheet("color: #ef4444; font-weight: bold; font-size: 14px;")
            self.val_chatgpt_status.setText("Disconnected")
            self.val_chatgpt_status.setStyleSheet("color: #94a3b8; font-weight: bold; font-size: 14px;")
            self.val_login_status.setText("N/A")
            self.val_url.setText("N/A")
            self.btn_launch.setEnabled(True)
            self.btn_connect.setEnabled(False)
            self.btn_disconnect.setEnabled(False)
            self.btn_test.setEnabled(False)

    def _launch_browser(self) -> None:
        self._append_log("Launching dedicated browser instance...")

        async def _do_launch():
            try:
                await browser_manager.launch(headless=config.headless)
                self._append_log("Dedicated browser context successfully launched.")
                signals.browser_log.emit("Navigating to ChatGPT home page...")
                # force_fresh=True: always reload chatgpt.com so the persistent
                # session does NOT restore a stale draft from the previous run.
                await browser_manager.navigate_to_chatgpt(force_fresh=True)
                await self._async_test_connection()
            except Exception as e:
                self._append_log(f"Error launching browser: {e}")
                logger.error("Browser launch error: %s", e)

        task_manager.dispatch_coroutine(_do_launch())
        QTimer.singleShot(1500, self.update_ui_state)

    def _navigate_chatgpt(self) -> None:
        self._append_log("Navigating browser to ChatGPT...")

        async def _do_nav():
            try:
                await browser_manager.navigate_to_chatgpt()
                self._append_log("Navigation completed.")
                await self._async_test_connection()
            except Exception as e:
                self._append_log(f"Navigation error: {e}")

        task_manager.dispatch_coroutine(_do_nav())

    def _test_connection(self) -> None:
        self._append_log("Testing connection and ChatGPT page state...")
        task_manager.dispatch_coroutine(self._async_test_connection())

    async def _async_test_connection(self) -> None:
        result = await browser_manager.check_connection()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Update labels safely
        self.val_last_check.setText(now_str)
        self.val_url.setText(result.get("url", "N/A"))

        if result.get("chatgpt_accessible"):
            self.val_chatgpt_status.setText("Accessible (200 OK)")
            self.val_chatgpt_status.setStyleSheet("color: #34d399; font-weight: bold; font-size: 14px;")
        else:
            self.val_chatgpt_status.setText("Not on ChatGPT")
            self.val_chatgpt_status.setStyleSheet("color: #f59e0b; font-weight: bold; font-size: 14px;")

        if result.get("is_logged_in"):
            self.val_login_status.setText("Logged In & Ready")
            self.val_login_status.setStyleSheet("color: #34d399; font-weight: bold; font-size: 14px;")
        else:
            self.val_login_status.setText("Login Required / Not Detected")
            self.val_login_status.setStyleSheet("color: #f59e0b; font-weight: bold; font-size: 14px;")

        msg = result.get("message", "")
        self._append_log(f"Check result: {msg} (URL: {result.get('url')})")
        signals.browser_status_changed.emit(
            "Running" if result.get("browser_running") else "Stopped",
            "Ready" if result.get("page_ready") else "Waiting",
            result.get("url", "")
        )
        self.update_ui_state()

    def _close_browser(self) -> None:
        self._append_log("Closing browser context...")

        async def _do_close():
            await browser_manager.close()
            self._append_log("Browser closed.")

        task_manager.dispatch_coroutine(_do_close())
        QTimer.singleShot(1000, self.update_ui_state)
