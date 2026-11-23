"""Processing Queue panel displaying persistent jobs, progress, and controls."""
from __future__ import annotations

from pathlib import Path
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox,
    QProgressBar, QAbstractItemView
)
from app.database import db
from app.models import JobStatus
from app.automation.job_queue import job_queue
from app.automation.task_manager import task_manager
from app.browser.browser_manager import browser_manager
from app.utils.signals import signals
from app.utils.logger import logger


from app.storage.file_manager import file_manager


class QueuePanel(QWidget):
    """Processing Queue management panel."""

    def __init__(self):
        super().__init__()
        self._init_ui()
        self._connect_signals()
        self.load_jobs_from_db()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(16)

        # Header
        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("Processing Queue")
        title.setStyleSheet("font-size: 26px; font-weight: bold; color: #f8fafc;")

        self.batch_info_lbl = QLabel(f"Folder: Desktop/XInvora Photos/{file_manager.get_or_create_batch_folder().name}")
        self.batch_info_lbl.setStyleSheet("color: #38bdf8; font-size: 13px; font-weight: 600;")

        self.queue_info_lbl = QLabel("Queue Status: IDLE | Total Jobs: 0")
        self.queue_info_lbl.setStyleSheet("color: #94a3b8; font-size: 12px;")

        title_box.addWidget(title)
        title_box.addWidget(self.batch_info_lbl)
        title_box.addWidget(self.queue_info_lbl)
        header.addLayout(title_box)

        header.addStretch()

        # Action Buttons
        self.btn_new_batch = QPushButton("+ Start New Batch")
        self.btn_new_batch.setStyleSheet("""
            QPushButton {
                background-color: #0ea5e9;
                color: #ffffff;
                font-weight: bold;
                border-radius: 6px;
                padding: 10px 16px;
                font-size: 13px;
            }
            QPushButton:hover { background-color: #0284c7; }
        """)
        self.btn_new_batch.clicked.connect(self._create_new_batch)
        header.addWidget(self.btn_new_batch)

        self.btn_generate = QPushButton("Build Queue Matrix")
        self.btn_generate.setStyleSheet("""
            QPushButton {
                background-color: #8b5cf6;
                color: #ffffff;
                font-weight: bold;
                border-radius: 6px;
                padding: 10px 18px;
            }
            QPushButton:hover { background-color: #7c3aed; }
        """)
        self.btn_generate.clicked.connect(self._build_queue_matrix)
        header.addWidget(self.btn_generate)

        self.btn_start = QPushButton("Start Processing")
        self.btn_start.setStyleSheet("""
            QPushButton {
                background-color: #6366f1;
                color: #ffffff;
                font-weight: bold;
                border-radius: 6px;
                padding: 10px 18px;
            }
            QPushButton:hover { background-color: #4f46e5; }
        """)
        self.btn_start.clicked.connect(self._start_processing)
        header.addWidget(self.btn_start)

        self.btn_pause = QPushButton("Pause")
        self.btn_pause.setStyleSheet("""
            QPushButton {
                background-color: #334155;
                color: #ffffff;
                border-radius: 6px;
                padding: 10px 16px;
            }
            QPushButton:hover { background-color: #475569; }
        """)
        self.btn_pause.clicked.connect(job_queue.pause)
        header.addWidget(self.btn_pause)

        self.btn_resume = QPushButton("Resume")
        self.btn_resume.setStyleSheet("""
            QPushButton {
                background-color: #334155;
                color: #ffffff;
                border-radius: 6px;
                padding: 10px 16px;
            }
            QPushButton:hover { background-color: #475569; }
        """)
        self.btn_resume.clicked.connect(job_queue.resume)
        header.addWidget(self.btn_resume)

        self.btn_clear = QPushButton("Clear Queue")
        self.btn_clear.setStyleSheet("""
            QPushButton {
                background-color: #dc2626;
                color: #ffffff;
                border-radius: 6px;
                padding: 10px 16px;
            }
            QPushButton:hover { background-color: #b91c1c; }
        """)
        self.btn_clear.clicked.connect(self._clear_queue)
        header.addWidget(self.btn_clear)

        layout.addLayout(header)

        # Retry and Selection Toolbar
        sub_bar = QHBoxLayout()
        sub_bar.setSpacing(10)

        self.btn_select_all = QPushButton("Select All")
        self.btn_select_all.setStyleSheet("""
            QPushButton {
                background-color: #1e293b;
                color: #cbd5e1;
                border: 1px solid #475569;
                border-radius: 6px;
                padding: 7px 14px;
                font-size: 12px;
            }
            QPushButton:hover { background-color: #334155; color: #ffffff; }
        """)
        self.btn_select_all.clicked.connect(self._toggle_select_all)
        sub_bar.addWidget(self.btn_select_all)

        self.btn_retry_selected = QPushButton("↻ Retry Selected Jobs")
        self.btn_retry_selected.setStyleSheet("""
            QPushButton {
                background-color: #f59e0b;
                color: #0f172a;
                font-weight: bold;
                border-radius: 6px;
                padding: 7px 16px;
                font-size: 13px;
            }
            QPushButton:hover { background-color: #d97706; }
        """)
        self.btn_retry_selected.clicked.connect(self._retry_selected)
        sub_bar.addWidget(self.btn_retry_selected)

        self.btn_retry_failed = QPushButton("↻ Retry All Failed")
        self.btn_retry_failed.setStyleSheet("""
            QPushButton {
                background-color: #ea580c;
                color: #ffffff;
                font-weight: bold;
                border-radius: 6px;
                padding: 7px 16px;
                font-size: 13px;
            }
            QPushButton:hover { background-color: #c2410c; }
        """)
        self.btn_retry_failed.clicked.connect(self._retry_all_failed)
        sub_bar.addWidget(self.btn_retry_failed)

        sub_bar.addStretch()
        layout.addLayout(sub_bar)

        # Progress Bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                background-color: #1e1e2d;
                border: 1px solid #334155;
                border-radius: 4px;
                height: 14px;
                text-align: center;
                color: #f8fafc;
                font-size: 11px;
            }
            QProgressBar::chunk {
                background-color: #6366f1;
                border-radius: 3px;
            }
        """)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        # Jobs Table
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels([
            "Select / Job ID", "Source Image", "Prompt Snapshot", "Status", "Retries", "Output File", "Error Message"
        ])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        self.table.setStyleSheet("""
            QTableWidget {
                background-color: #1e1e2d;
                border: 1px solid #2d2d42;
                border-radius: 8px;
                color: #f8fafc;
                gridline-color: #2d2d42;
            }
            QHeaderView::section {
                background-color: #171723;
                color: #94a3b8;
                font-weight: 600;
                padding: 8px;
                border: none;
                border-bottom: 1px solid #2d2d42;
            }
            QTableWidget::item:selected {
                background-color: #3b82f6;
            }
        """)
        layout.addWidget(self.table)

    def _connect_signals(self) -> None:
        signals.jobs_updated.connect(self.load_jobs_from_db)
        signals.queue_progress.connect(self._on_progress)
        signals.queue_state_changed.connect(self._on_state_changed)

    def _on_progress(self, completed: int, total: int) -> None:
        if total > 0:
            pct = int((completed / total) * 100)
            self.progress_bar.setValue(pct)
            self.progress_bar.setFormat(f"{completed} / {total} Jobs Completed ({pct}%)")
        else:
            self.progress_bar.setValue(0)

    def _on_state_changed(self, state: str) -> None:
        jobs = db.get_all_jobs()
        self.queue_info_lbl.setText(f"Queue Status: {state} | Total Jobs: {len(jobs)}")
        if state == "RUNNING":
            self.btn_start.setEnabled(False)
            self.btn_start.setText("Processing...")
        else:
            self.btn_start.setEnabled(True)
            self.btn_start.setText("Start Processing")

    def load_jobs_from_db(self) -> None:
        jobs = db.get_all_jobs()
        self.table.setRowCount(len(jobs))

        completed = len([j for j in jobs if j.status == JobStatus.COMPLETED])
        self._on_progress(completed, len(jobs))
        self.queue_info_lbl.setText(f"Total Jobs: {len(jobs)} ({completed} completed)")

        for row_idx, j in enumerate(jobs):
            # Job ID with Checkbox
            id_item = QTableWidgetItem(f"#{j.id}")
            id_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            id_item.setCheckState(Qt.Unchecked)
            id_item.setData(Qt.UserRole, j.id)
            self.table.setItem(row_idx, 0, id_item)

            # Image
            img_name = Path(j.image_path).name
            self.table.setItem(row_idx, 1, QTableWidgetItem(img_name))

            # Prompt Snapshot
            prompt_preview = j.prompt_text if len(j.prompt_text) < 70 else f"{j.prompt_text[:67]}..."
            self.table.setItem(row_idx, 2, QTableWidgetItem(prompt_preview))

            # Status with color formatting
            status_item = QTableWidgetItem(j.status.value)
            status_item.setTextAlignment(Qt.AlignCenter)
            if j.status == JobStatus.COMPLETED:
                status_item.setForeground(Qt.green)
            elif j.status in (JobStatus.GENERATING, JobStatus.UPLOADING, JobStatus.DOWNLOADING, JobStatus.VERIFYING):
                status_item.setForeground(Qt.cyan)
            elif j.status == JobStatus.FAILED:
                status_item.setForeground(Qt.red)
            elif j.status == JobStatus.PENDING:
                status_item.setForeground(Qt.yellow)
            self.table.setItem(row_idx, 3, status_item)

            # Retries
            retries_item = QTableWidgetItem(str(j.retry_count))
            retries_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row_idx, 4, retries_item)

            # Output File
            output_str = Path(j.output_path).name if j.output_path else "-"
            self.table.setItem(row_idx, 5, QTableWidgetItem(output_str))

            # Error Message
            err_str = j.error_message or "-"
            self.table.setItem(row_idx, 6, QTableWidgetItem(err_str))

            self.table.setRowHeight(row_idx, 38)

    def _toggle_select_all(self) -> None:
        """Toggles check state for all rows."""
        any_unchecked = False
        for r in range(self.table.rowCount()):
            item = self.table.item(r, 0)
            if item and item.checkState() == Qt.Unchecked:
                any_unchecked = True
                break

        new_state = Qt.Checked if any_unchecked else Qt.Unchecked
        for r in range(self.table.rowCount()):
            item = self.table.item(r, 0)
            if item:
                item.setCheckState(new_state)

        self.btn_select_all.setText("Deselect All" if any_unchecked else "Select All")

    def _get_selected_or_checked_job_ids(self) -> list[int]:
        """Gathers job IDs that are either checked or highlighted via row selection."""
        job_ids = set()
        for r in range(self.table.rowCount()):
            item = self.table.item(r, 0)
            if item and item.checkState() == Qt.Checked:
                j_id = item.data(Qt.UserRole)
                if j_id:
                    job_ids.add(int(j_id))

        # Also include any highlighted rows in selection
        for idx in self.table.selectedIndexes():
            item = self.table.item(idx.row(), 0)
            if item:
                j_id = item.data(Qt.UserRole)
                if j_id:
                    job_ids.add(int(j_id))

        return sorted(job_ids)

    def _retry_selected(self) -> None:
        """Resets selected/checked jobs to PENDING and restarts generation."""
        job_ids = self._get_selected_or_checked_job_ids()
        if not job_ids:
            QMessageBox.information(
                self,
                "Select Jobs to Retry",
                "Please check or select the jobs you want to retry (works for both failed and completed thumbnails you wish to regenerate)."
            )
            return

        count = job_queue.retry_jobs(job_ids)
        self.load_jobs_from_db()
        signals.status_message.emit(f"Reset {count} job(s) for retry.", 3000)

        if browser_manager.is_running:
            task_manager.start_pipeline()
            signals.status_message.emit(f"Restarted processing for {count} retried job(s).", 4000)
        else:
            QMessageBox.information(
                self,
                "Jobs Ready",
                f"{count} job(s) reset to PENDING. Ensure Chrome is connected and click 'Start Processing'."
            )

    def _retry_all_failed(self) -> None:
        """Resets all FAILED jobs to PENDING and restarts generation."""
        failed_jobs = [j for j in db.get_all_jobs() if j.status == JobStatus.FAILED]
        if not failed_jobs:
            QMessageBox.information(self, "No Failed Jobs", "There are currently no failed jobs in the queue.")
            return

        count = job_queue.retry_failed_jobs()
        self.load_jobs_from_db()
        signals.status_message.emit(f"Reset {count} failed job(s) for retry.", 3000)

        if browser_manager.is_running:
            task_manager.start_pipeline()
            signals.status_message.emit(f"Restarted processing for {count} failed job(s).", 4000)
        else:
            QMessageBox.information(
                self,
                "Jobs Ready",
                f"{count} failed job(s) reset to PENDING. Ensure Chrome is connected and click 'Start Processing'."
            )

    def _create_new_batch(self) -> None:
        new_batch = file_manager.create_new_batch()
        self.batch_info_lbl.setText(f"Folder: Desktop/XInvora Photos/{new_batch.name}")
        signals.status_message.emit(f"Started new batch: {new_batch.name}", 4000)
        QMessageBox.information(
            self,
            "New Batch Started",
            f"Created new batch folder:\nDesktop/XInvora Photos/{new_batch.name}\n\nAll subsequent generations will save directly into this batch."
        )

    def _build_queue_matrix(self) -> None:
        images = db.get_all_images()
        prompts = [p for p in db.get_all_prompts() if p.is_enabled]

        if not images:
            QMessageBox.warning(self, "No Images", "Please upload at least one image in the Image Manager tab.")
            return

        if not prompts:
            QMessageBox.warning(self, "No Prompts", "Please create and enable at least one prompt in the Prompt Library.")
            return

        created = job_queue.populate_jobs(images, prompts)
        self.load_jobs_from_db()
        signals.status_message.emit(
            f"Built queue matrix: {len(images)} images × {len(prompts)} prompts = {len(created)} jobs added.",
            4000
        )

    def _start_processing(self) -> None:
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
                "No Pending Jobs",
                "There are no pending jobs to execute. Click 'Build Queue Matrix' first."
            )
            return

        task_manager.start_pipeline()
        signals.status_message.emit("Queue processing pipeline started.", 3000)

    def _clear_queue(self) -> None:
        if QMessageBox.question(
            self, "Confirm Clear", "Are you sure you want to clear all jobs from the queue?"
        ) == QMessageBox.Yes:
            db.clear_all_jobs()
            self.load_jobs_from_db()
            signals.jobs_updated.emit()
            signals.status_message.emit("Queue cleared.", 3000)
