"""Generated Images gallery panel displaying completed outputs, thumbnails, and file actions."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QPixmap, QIcon
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox,
    QAbstractItemView
)
from app.config import config
from app.database import db
from app.utils.signals import signals


class GeneratedImagesPanel(QWidget):
    """Gallery panel showing verified generated image outputs."""

    def __init__(self):
        super().__init__()
        self._init_ui()
        self._connect_signals()
        self.load_outputs_from_db()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(16)

        # Header
        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("Generated Images")
        title.setStyleSheet("font-size: 26px; font-weight: bold; color: #f8fafc;")
        self.count_lbl = QLabel("Total Generated Outputs: 0")
        self.count_lbl.setStyleSheet("color: #94a3b8; font-size: 13px;")
        title_box.addWidget(title)
        title_box.addWidget(self.count_lbl)
        header.addLayout(title_box)

        header.addStretch()

        self.btn_open_folder = QPushButton("Open Outputs Folder")
        self.btn_open_folder.setStyleSheet("""
            QPushButton {
                background-color: #6366f1;
                color: #ffffff;
                font-weight: bold;
                border-radius: 6px;
                padding: 10px 18px;
            }
            QPushButton:hover { background-color: #4f46e5; }
        """)
        self.btn_open_folder.clicked.connect(self._open_folder)
        header.addWidget(self.btn_open_folder)

        self.btn_refresh = QPushButton("Refresh")
        self.btn_refresh.setStyleSheet("""
            QPushButton {
                background-color: #334155;
                color: #f1f5f9;
                border-radius: 6px;
                padding: 10px 16px;
            }
            QPushButton:hover { background-color: #475569; }
        """)
        self.btn_refresh.clicked.connect(self.load_outputs_from_db)
        header.addWidget(self.btn_refresh)

        layout.addLayout(header)

        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels([
            "Preview", "Output Filename", "Dimensions", "File Size", "Created At", "File Path"
        ])
        self.table.setIconSize(QSize(64, 64))
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
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
        self.table.cellDoubleClicked.connect(lambda r, c: self._open_selected_image())
        layout.addWidget(self.table)

    def _connect_signals(self) -> None:
        signals.download_completed.connect(lambda j, p: self.load_outputs_from_db())

    def load_outputs_from_db(self) -> None:
        outputs = db.get_all_outputs()
        self.count_lbl.setText(f"Total Generated Outputs: {len(outputs)}")
        self.table.setRowCount(len(outputs))

        for row_idx, item in enumerate(outputs):
            path = Path(item.file_path)

            # Thumbnail
            pixmap = QPixmap(str(path))
            thumb = QTableWidgetItem()
            if not pixmap.isNull():
                thumb.setIcon(QIcon(pixmap.scaled(64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation)))
            elif path.suffix.lower() == ".md":
                thumb.setText("[MD Doc]")
                thumb.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row_idx, 0, thumb)

            # Filename
            self.table.setItem(row_idx, 1, QTableWidgetItem(path.name))

            # Dimensions
            dim_str = f"{item.width} x {item.height}" if item.width > 0 else "Markdown Text"
            self.table.setItem(row_idx, 2, QTableWidgetItem(dim_str))

            # Size
            size_kb = item.file_size / 1024.0
            size_str = f"{size_kb:.1f} KB" if size_kb < 1024 else f"{(size_kb/1024.0):.2f} MB"
            self.table.setItem(row_idx, 3, QTableWidgetItem(size_str))

            # Date
            date_str = item.created_at[:19].replace("T", " ") if item.created_at else ""
            self.table.setItem(row_idx, 4, QTableWidgetItem(date_str))

            # Full Path
            path_item = QTableWidgetItem(str(path.resolve()))
            path_item.setData(Qt.UserRole, str(path.resolve()))
            self.table.setItem(row_idx, 5, path_item)

            self.table.setRowHeight(row_idx, 72)

    def _open_selected_image(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        path_item = self.table.item(row, 5)
        if not path_item:
            return
        full_path = path_item.data(Qt.UserRole)
        if full_path and Path(full_path).exists():
            if sys.platform == "win32":
                subprocess.Popen(["explorer", full_path])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", full_path])
            else:
                subprocess.Popen(["xdg-open", full_path])

    def _open_folder(self) -> None:
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
