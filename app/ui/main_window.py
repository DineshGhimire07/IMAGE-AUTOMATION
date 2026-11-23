"""Main Application Window for XINVORA AI Studio with sidebar navigation."""
from __future__ import annotations

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon, QFont
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QPushButton,
    QStackedWidget, QLabel, QStatusBar, QFrame
)
from app.config import config
from app.ui.dashboard import DashboardPanel
from app.ui.image_manager import ImageManagerPanel
from app.ui.prompt_manager import PromptManagerPanel
from app.ui.browser_panel import BrowserPanel
from app.ui.queue_panel import QueuePanel
from app.ui.generated_images import GeneratedImagesPanel
from app.ui.settings_panel import SettingsPanel
from app.automation.task_manager import task_manager
from app.browser.browser_manager import browser_manager
from app.utils.signals import signals
from app.utils.logger import logger


class NavButton(QPushButton):
    """Sidebar navigation button with active highlight indicator."""

    def __init__(self, text: str, index: int, on_click):
        super().__init__(text)
        self.index = index
        self.setCheckable(True)
        self.setAutoExclusive(True)
        self.setFixedHeight(44)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet("""
            QPushButton {
                text-align: left;
                padding-left: 18px;
                font-size: 13px;
                font-weight: 500;
                color: #94a3b8;
                background-color: transparent;
                border: none;
                border-left: 3px solid transparent;
                border-radius: 0px;
            }
            QPushButton:hover {
                color: #f1f5f9;
                background-color: #1e1e2d;
            }
            QPushButton:checked {
                color: #ffffff;
                font-weight: 600;
                background-color: #1e1e2d;
                border-left: 3px solid #6366f1;
            }
        """)
        self.clicked.connect(lambda: on_click(self.index))


class MainWindow(QMainWindow):
    """Main application window for XINVORA AI Studio."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{config.app_name} v{config.version}")
        self.resize(1280, 800)
        self.setMinimumSize(1024, 680)

        self._apply_global_styles()
        self._init_layout()
        self._connect_signals()

        # Set default view to Dashboard
        self.nav_buttons[0].setChecked(True)
        self.stack.setCurrentIndex(0)

    def _apply_global_styles(self) -> None:
        self.setStyleSheet("""
            QMainWindow {
                background-color: #0f111a;
            }
            QWidget {
                color: #f8fafc;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            }
            QStatusBar {
                background-color: #13141f;
                color: #94a3b8;
                border-top: 1px solid #1e1e2d;
                font-size: 12px;
                padding: 4px 12px;
            }
            QScrollBar:vertical {
                background: #0f111a;
                width: 8px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background: #334155;
                min-height: 20px;
                border-radius: 4px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)

    def _init_layout(self) -> None:
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Left Sidebar
        sidebar = QFrame()
        sidebar.setFixedWidth(240)
        sidebar.setStyleSheet("""
            QFrame {
                background-color: #13141f;
                border-right: 1px solid #1e1e2d;
            }
        """)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 20, 0, 20)
        sidebar_layout.setSpacing(4)

        # App Brand Header
        brand_box = QVBoxLayout()
        brand_box.setContentsMargins(20, 0, 20, 24)
        brand_title = QLabel("XINVORA")
        brand_title.setStyleSheet("font-size: 18px; font-weight: 800; color: #ffffff; letter-spacing: 1.5px;")
        brand_sub = QLabel("AI STUDIO")
        brand_sub.setStyleSheet("font-size: 11px; font-weight: 600; color: #6366f1; letter-spacing: 2px;")
        brand_box.addWidget(brand_title)
        brand_box.addWidget(brand_sub)
        sidebar_layout.addLayout(brand_box)

        # Navigation buttons
        self.nav_buttons: list[NavButton] = []
        nav_items = [
            ("Dashboard", 0),
            ("Image Manager", 1),
            ("Prompt Library", 2),
            ("Chrome Connection", 3),
            ("Processing Queue", 4),
            ("Generated Images", 5),
            ("Settings", 6),
        ]

        for label, idx in nav_items:
            btn = NavButton(label, idx, self._switch_tab)
            self.nav_buttons.append(btn)
            sidebar_layout.addWidget(btn)

        sidebar_layout.addStretch()

        # Version stamp
        lbl_ver = QLabel(f"v{config.version}")
        lbl_ver.setStyleSheet("color: #475569; font-size: 11px; padding-left: 20px;")
        sidebar_layout.addWidget(lbl_ver)

        main_layout.addWidget(sidebar)

        # Main Content Stack
        self.stack = QStackedWidget()
        self.stack.setStyleSheet("background-color: #0f111a;")

        # Instantiate panel pages
        self.dashboard_panel = DashboardPanel()
        self.image_manager_panel = ImageManagerPanel()
        self.prompt_manager_panel = PromptManagerPanel()
        self.browser_panel = BrowserPanel()
        self.queue_panel = QueuePanel()
        self.generated_images_panel = GeneratedImagesPanel()
        self.settings_panel = SettingsPanel()

        self.stack.addWidget(self.dashboard_panel)
        self.stack.addWidget(self.image_manager_panel)
        self.stack.addWidget(self.prompt_manager_panel)
        self.stack.addWidget(self.browser_panel)
        self.stack.addWidget(self.queue_panel)
        self.stack.addWidget(self.generated_images_panel)
        self.stack.addWidget(self.settings_panel)

        main_layout.addWidget(self.stack)

        # Status Bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready. Dedicated Chrome environment prepared.")

    def _switch_tab(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        # Refresh current panel if needed
        current_widget = self.stack.currentWidget()
        if hasattr(current_widget, "refresh_stats"):
            current_widget.refresh_stats()
        elif hasattr(current_widget, "load_images_from_db"):
            current_widget.load_images_from_db()
        elif hasattr(current_widget, "load_prompts_from_db"):
            current_widget.load_prompts_from_db()
        elif hasattr(current_widget, "load_jobs_from_db"):
            current_widget.load_jobs_from_db()
        elif hasattr(current_widget, "load_outputs_from_db"):
            current_widget.load_outputs_from_db()

    def _connect_signals(self) -> None:
        signals.status_message.connect(self._show_status)

    def _show_status(self, msg: str, timeout: int = 3000) -> None:
        self.status_bar.showMessage(msg, timeout)

    def closeEvent(self, event) -> None:
        """Gracefully cleanup background asyncio threads and browser context."""
        logger.info("Application closing. Cleaning up background services...")
        try:
            task_manager.stop_loop()
        except Exception as e:
            logger.warning("Error stopping task manager thread: %s", e)
        event.accept()
