"""Image Manager panel for uploading, inspecting, and managing input images."""
from __future__ import annotations

from pathlib import Path
from typing import List
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QPixmap, QIcon, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFileDialog, QTableWidget, QTableWidgetItem, QHeaderView,
    QMessageBox, QAbstractItemView, QFrame
)
from app.database import db
from app.models import ImageItem
from app.storage.image_validator import ImageValidator, SUPPORTED_EXTENSIONS
from app.utils.signals import signals
from app.utils.logger import logger


class ImageDropArea(QFrame):
    """Drag and drop drop-zone widget."""

    def __init__(self, on_files_dropped):
        super().__init__()
        self.on_files_dropped = on_files_dropped
        self.setAcceptDrops(True)
        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet("""
            QFrame {
                border: 2px dashed #475569;
                border-radius: 8px;
                background-color: #1e1e2d;
                padding: 16px;
            }
            QFrame:hover {
                border-color: #6366f1;
                background-color: #26263a;
            }
        """)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        self.lbl = QLabel("Drag & Drop Images Here (JPG, PNG, WEBP) or click 'Select Images'")
        self.lbl.setStyleSheet("color: #94a3b8; font-size: 14px; font-weight: 500;")
        layout.addWidget(self.lbl)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        file_paths = []
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            if path.suffix.lower() in SUPPORTED_EXTENSIONS:
                file_paths.append(path)
        if file_paths:
            self.on_files_dropped(file_paths)
            event.acceptProposedAction()


class ImageManagerPanel(QWidget):
    """Full-featured Image Manager panel with thumbnails, deduplication, and metadata."""

    def __init__(self):
        super().__init__()
        self._init_ui()
        self.load_images_from_db()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(16)

        # Header
        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("Image Manager")
        title.setStyleSheet("font-size: 26px; font-weight: bold; color: #f8fafc;")
        self.count_lbl = QLabel("Total Images: 0")
        self.count_lbl.setStyleSheet("color: #94a3b8; font-size: 13px;")
        title_box.addWidget(title)
        title_box.addWidget(self.count_lbl)
        header.addLayout(title_box)

        header.addStretch()

        # Action buttons
        self.btn_select = QPushButton("Select Images...")
        self.btn_select.setStyleSheet("""
            QPushButton {
                background-color: #6366f1;
                color: #ffffff;
                font-weight: bold;
                border-radius: 6px;
                padding: 10px 18px;
            }
            QPushButton:hover { background-color: #4f46e5; }
        """)
        self.btn_select.clicked.connect(self._open_file_dialog)
        header.addWidget(self.btn_select)

        self.btn_remove = QPushButton("Remove Selected")
        self.btn_remove.setStyleSheet("""
            QPushButton {
                background-color: #334155;
                color: #f1f5f9;
                border-radius: 6px;
                padding: 10px 16px;
            }
            QPushButton:hover { background-color: #475569; }
        """)
        self.btn_remove.clicked.connect(self._remove_selected)
        header.addWidget(self.btn_remove)

        self.btn_clear = QPushButton("Clear All")
        self.btn_clear.setStyleSheet("""
            QPushButton {
                background-color: #dc2626;
                color: #ffffff;
                border-radius: 6px;
                padding: 10px 16px;
            }
            QPushButton:hover { background-color: #b91c1c; }
        """)
        self.btn_clear.clicked.connect(self._clear_all)
        header.addWidget(self.btn_clear)

        layout.addLayout(header)

        # Drop Zone
        self.drop_area = ImageDropArea(self.import_image_files)
        layout.addWidget(self.drop_area)

        # Images Table
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels([
            "Thumbnail", "Original Filename", "Dimensions", "Size", "Checksum (SHA-256)", "Original Path"
        ])
        self.table.setIconSize(QSize(60, 60))
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
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
        layout.addWidget(self.table)

    def _open_file_dialog(self) -> None:
        filter_str = "Images (*.png *.jpg *.jpeg *.webp)"
        files, _ = QFileDialog.getOpenFileNames(
            self, "Select Images for Studio", "", filter_str,
            options=QFileDialog.Option.DontUseNativeDialog
        )
        if files:
            paths = [Path(f) for f in files]
            self.import_image_files(paths)

    def import_image_files(self, paths: List[Path]) -> None:
        added_count = 0
        skipped_duplicates = 0
        invalid_count = 0

        for path in paths:
            try:
                meta = ImageValidator.validate_image_file(path)
                item = ImageItem(
                    id=None,
                    original_path=meta["path"],
                    filename=meta["filename"],
                    width=meta["width"],
                    height=meta["height"],
                    file_size=meta["file_size"],
                    checksum=meta["checksum"],
                )
                img_id = db.insert_image(item)
                if img_id is not None:
                    added_count += 1
                else:
                    skipped_duplicates += 1
            except Exception as e:
                logger.warning("Skipped invalid file %s: %s", path.name, e)
                invalid_count += 1

        self.load_images_from_db()
        signals.images_updated.emit()

        msg = f"Imported {added_count} image(s)."
        if skipped_duplicates > 0:
            msg += f" {skipped_duplicates} duplicate(s) skipped."
        if invalid_count > 0:
            msg += f" {invalid_count} invalid file(s) ignored."

        signals.status_message.emit(msg, 4000)

    def load_images_from_db(self) -> None:
        images = db.get_all_images()
        self.count_lbl.setText(f"Total Images: {len(images)}")
        self.table.setRowCount(len(images))

        for row_idx, img in enumerate(images):
            # Thumbnail
            pixmap = QPixmap(img.original_path)
            thumb_item = QTableWidgetItem()
            if not pixmap.isNull():
                scaled = pixmap.scaled(60, 60, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                thumb_item.setIcon(QIcon(scaled))
            self.table.setItem(row_idx, 0, thumb_item)

            # Name (store db id in UserRole)
            name_item = QTableWidgetItem(img.filename)
            name_item.setData(Qt.UserRole, img.id)
            self.table.setItem(row_idx, 1, name_item)

            # Dimensions
            dim_item = QTableWidgetItem(f"{img.width} x {img.height}")
            self.table.setItem(row_idx, 2, dim_item)

            # Size
            size_kb = img.file_size / 1024.0
            size_str = f"{size_kb:.1f} KB" if size_kb < 1024 else f"{(size_kb/1024.0):.2f} MB"
            self.table.setItem(row_idx, 3, QTableWidgetItem(size_str))

            # Checksum
            short_hash = f"{img.checksum[:12]}..."
            self.table.setItem(row_idx, 4, QTableWidgetItem(short_hash))

            # Full path
            self.table.setItem(row_idx, 5, QTableWidgetItem(img.original_path))

            self.table.setRowHeight(row_idx, 68)

    def _remove_selected(self) -> None:
        selected_rows = sorted(set(idx.row() for idx in self.table.selectedIndexes()), reverse=True)
        if not selected_rows:
            return

        for row in selected_rows:
            name_item = self.table.item(row, 1)
            if name_item:
                img_id = name_item.data(Qt.UserRole)
                if img_id:
                    db.delete_image(int(img_id))

        self.load_images_from_db()
        signals.images_updated.emit()
        signals.status_message.emit("Selected image(s) removed.", 3000)

    def _clear_all(self) -> None:
        if QMessageBox.question(
            self, "Confirm Clear All", "Are you sure you want to remove all imported images?"
        ) == QMessageBox.Yes:
            db.clear_all_images()
            self.load_images_from_db()
            signals.images_updated.emit()
            signals.status_message.emit("All images cleared.", 3000)
