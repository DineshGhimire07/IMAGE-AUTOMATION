"""Dashboard panel providing real-time metrics, status indicators, and pipeline controls."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QGridLayout, QMessageBox, QScrollArea
)
from app.config import config
from app.database import db
from app.models import JobStatus
from app.automation.task_manager import task_manager
from app.automation.job_queue import job_queue
from app.browser.browser_manager import browser_manager
from app.utils.signals import signals
from app.utils.logger import logger


class StatCard(QFrame):
    """Reusable metric display card."""

    def __init__(self, title: str, initial_value: str = "0", color: str = "#8b5cf6"):
        super().__init__()
        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet(f"""
            QFrame {{
                background-color: #1e1e2d;
                border-radius: 8px;
                border: 1px solid #2d2d42;
                padding: 12px;
            }}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)

        self.title_label = QLabel(title.upper())
        self.title_label.setStyleSheet("color: #94a3b8; font-size: 11px; font-weight: 600; letter-spacing: 0.5px;")

        self.value_label = QLabel(initial_value)
        self.value_label.setStyleSheet(f"color: {color}; font-size: 24px; font-weight: bold;")

        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)

    def set_value(self, value: str) -> None:
        self.value_label.setText(str(value))


class DashboardPanel(QWidget):
    """Main dashboard displaying live operations, metrics, and global controls."""

    def __init__(self):
        super().__init__()
        self._init_ui()
        self._connect_signals()
        self.refresh_stats()

    def _init_ui(self) -> None:
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(24)

        # Header
        header_layout = QVBoxLayout()
        title = QLabel("Dashboard")
        title.setStyleSheet("font-size: 26px; font-weight: bold; color: #f8fafc;")
        subtitle = QLabel("Live overview of image generation, browser session, and processing queue.")
        subtitle.setStyleSheet("color: #94a3b8; font-size: 13px;")
        header_layout.addWidget(title)
        header_layout.addWidget(subtitle)
        layout.addLayout(header_layout)

        # Stat cards grid
        self.grid = QGridLayout()
        self.grid.setSpacing(16)

        self.card_images = StatCard("Uploaded Images", "0", "#38bdf8")
        self.card_prompts = StatCard("Active Prompts", "0", "#a78bfa")
        self.card_total_jobs = StatCard("Total Jobs", "0", "#f1f5f9")
        self.card_pending_jobs = StatCard("Pending Jobs", "0", "#fbbf24")
        self.card_completed_jobs = StatCard("Completed Jobs", "0", "#34d399")
        self.card_failed_jobs = StatCard("Failed Jobs", "0", "#f87171")

        self.grid.addWidget(self.card_images, 0, 0)
        self.grid.addWidget(self.card_prompts, 0, 1)
        self.grid.addWidget(self.card_total_jobs, 0, 2)
        self.grid.addWidget(self.card_pending_jobs, 1, 0)
        self.grid.addWidget(self.card_completed_jobs, 1, 1)
        self.grid.addWidget(self.card_failed_jobs, 1, 2)

        layout.addLayout(self.grid)

        # Status and Operational details frame
        status_frame = QFrame()
        status_frame.setStyleSheet("""
            QFrame {{
                background-color: #1e1e2d;
                border-radius: 8px;
                border: 1px solid #2d2d42;
                padding: 16px;
            }}
        """)
        sf_layout = QVBoxLayout(status_frame)
        sf_layout.setSpacing(12)

        section_title = QLabel("System Status")
        section_title.setStyleSheet("font-size: 16px; font-weight: bold; color: #f8fafc;")
        sf_layout.addWidget(section_title)

        self.browser_status_lbl = QLabel("Browser Connection: Not Running")
        self.browser_status_lbl.setStyleSheet("color: #cbd5e1; font-size: 13px;")
        sf_layout.addWidget(self.browser_status_lbl)

        self.active_job_lbl = QLabel("Currently Processing: None (Queue Idle)")
        self.active_job_lbl.setStyleSheet("color: #cbd5e1; font-size: 13px;")
        sf_layout.addWidget(self.active_job_lbl)

        self.workers_lbl = QLabel(f"Download Workers: {config.download_workers_count} Active Background Workers")
        self.workers_lbl.setStyleSheet("color: #cbd5e1; font-size: 13px;")
        sf_layout.addWidget(self.workers_lbl)

        layout.addWidget(status_frame)

        # Global Control Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)

        self.btn_start = QPushButton("Start Processing")
        self.btn_start.setStyleSheet("""
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
        self.btn_start.clicked.connect(self._on_start_processing)
        btn_layout.addWidget(self.btn_start)

        self.btn_pause = QPushButton("Pause")
        self.btn_pause.setStyleSheet("""
            QPushButton {
                background-color: #334155;
                color: #ffffff;
                border-radius: 6px;
                padding: 10px 18px;
                font-size: 13px;
            }
            QPushButton:hover { background-color: #475569; }
        """)
        self.btn_pause.clicked.connect(self._on_pause)
        btn_layout.addWidget(self.btn_pause)

        self.btn_resume = QPushButton("Resume")
        self.btn_resume.setStyleSheet("""
            QPushButton {
                background-color: #334155;
                color: #ffffff;
                border-radius: 6px;
                padding: 10px 18px;
                font-size: 13px;
            }
            QPushButton:hover { background-color: #475569; }
        """)
        self.btn_resume.clicked.connect(self._on_resume)
        btn_layout.addWidget(self.btn_resume)

        self.btn_cancel = QPushButton("Cancel Execution")
        self.btn_cancel.setStyleSheet("""
            QPushButton {
                background-color: #ef4444;
                color: #ffffff;
                border-radius: 6px;
                padding: 10px 18px;
                font-size: 13px;
            }
            QPushButton:hover { background-color: #dc2626; }
        """)
        self.btn_cancel.clicked.connect(self._on_cancel)
        btn_layout.addWidget(self.btn_cancel)

        btn_layout.addStretch()

        self.btn_open_output = QPushButton("Open Output Folder")
        self.btn_open_output.setStyleSheet("""
            QPushButton {
                background-color: #1e293b;
                color: #94a3b8;
                border: 1px solid #475569;
                border-radius: 6px;
                padding: 10px 16px;
                font-size: 13px;
            }
            QPushButton:hover { color: #f8fafc; border-color: #94a3b8; }
        """)
        self.btn_open_output.clicked.connect(self._open_output_folder)
        btn_layout.addWidget(self.btn_open_output)

        self.btn_open_logs = QPushButton("View Logs")
        self.btn_open_logs.setStyleSheet("""
            QPushButton {
                background-color: #1e293b;
                color: #94a3b8;
                border: 1px solid #475569;
                border-radius: 6px;
                padding: 10px 16px;
                font-size: 13px;
            }
            QPushButton:hover { color: #f8fafc; border-color: #94a3b8; }
        """)
        self.btn_open_logs.clicked.connect(self._open_logs)
        btn_layout.addWidget(self.btn_open_logs)

        layout.addLayout(btn_layout)
        layout.addStretch()

        scroll_layout = QVBoxLayout(self)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll.setWidget(container)
        scroll_layout.addWidget(scroll)

    def _connect_signals(self) -> None:
        signals.images_updated.connect(self.refresh_stats)
        signals.prompts_updated.connect(self.refresh_stats)
        signals.jobs_updated.connect(self.refresh_stats)
        signals.job_status_changed.connect(self._on_job_status_change)
        signals.browser_status_changed.connect(self._on_browser_status_change)
        signals.queue_state_changed.connect(self._on_queue_state_change)

        # Refresh stats timer
        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(3000)
        self.poll_timer.timeout.connect(self.refresh_stats)
        self.poll_timer.start()

    def refresh_stats(self) -> None:
        images = db.get_all_images()
        prompts = db.get_all_prompts()
        counts = db.get_job_counts_by_status()

        total_jobs = sum(counts.values())
        pending = counts.get(JobStatus.PENDING.value, 0)
        completed = counts.get(JobStatus.COMPLETED.value, 0)
        failed = counts.get(JobStatus.FAILED.value, 0)

        self.card_images.set_value(str(len(images)))
        self.card_prompts.set_value(str(len([p for p in prompts if p.is_enabled])))
        self.card_total_jobs.set_value(str(total_jobs))
        self.card_pending_jobs.set_value(str(pending))
        self.card_completed_jobs.set_value(str(completed))
        self.card_failed_jobs.set_value(str(failed))

        # Check browser state
        is_running = browser_manager.is_running
        self.browser_status_lbl.setText(
            f"Browser Connection: {'Running & Connected' if is_running else 'Disconnected / Not Running'}"
        )

    def _on_job_status_change(self, job_id: int, status: str, err: str) -> None:
        if status in ("UPLOADING", "GENERATING", "DOWNLOADING", "VERIFYING"):
            self.active_job_lbl.setText(f"Currently Processing: Job #{job_id} ({status})...")
        else:
            self.active_job_lbl.setText("Currently Processing: None (Queue Idle)")
        self.refresh_stats()

    def _on_browser_status_change(self, b_state: str, chat_state: str, url: str) -> None:
        self.browser_status_lbl.setText(f"Browser: {b_state} | ChatGPT: {chat_state} ({url})")

    def _on_queue_state_change(self, state: str) -> None:
        signals.status_message.emit(f"Queue State: {state}", 4000)
        if state == "RUNNING":
            self.btn_start.setEnabled(False)
            self.btn_start.setText("Processing...")
        else:
            self.btn_start.setEnabled(True)
            self.btn_start.setText("Start Processing")

    def _on_start_processing(self) -> None:
        if not browser_manager.is_running:
            QMessageBox.warning(
                self,
                "Browser Required",
                "Please launch and connect the dedicated Chrome browser first from the 'Chrome Connection' tab."
            )
            return

        pending = db.get_pending_jobs()
        if not pending:
            QMessageBox.information(
                self,
                "Queue Empty",
                "No pending jobs found. Add images and prompts, then generate queue items from the 'Processing Queue' tab."
            )
            return

        task_manager.start_pipeline()
        signals.status_message.emit("Pipeline processing started.", 3000)

    def _on_pause(self) -> None:
        job_queue.pause()

    def _on_resume(self) -> None:
        job_queue.resume()

    def _on_cancel(self) -> None:
        job_queue.stop()

    def _open_output_folder(self) -> None:
        from app.storage.file_manager import file_manager
        folder = file_manager.get_or_create_batch_folder()
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        if sys.platform == "win32":
            subprocess.Popen(["explorer", str(folder.resolve())])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(folder.resolve())])
        else:
            subprocess.Popen(["xdg-open", str(folder.resolve())])

    def _open_logs(self) -> None:
        logs_folder = config.logs_dir
        logs_folder.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            subprocess.Popen(["explorer", str(logs_folder.resolve())])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(logs_folder.resolve())])
        else:
            subprocess.Popen(["xdg-open", str(logs_folder.resolve())])
