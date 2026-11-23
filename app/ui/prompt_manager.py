"""Prompt Library panel for creating, editing, reordering, and enabling prompts."""
from __future__ import annotations

from datetime import datetime
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox,
    QDialog, QLineEdit, QTextEdit, QCheckBox, QAbstractItemView,
    QFrame
)
from app.database import db
from app.models import PromptItem
from app.utils.signals import signals
from app.utils.logger import logger


class PromptDialog(QDialog):
    """Dialog for creating or editing a Prompt."""

    def __init__(self, parent=None, prompt: PromptItem | None = None):
        super().__init__(parent)
        self.prompt = prompt
        self.setWindowTitle("Edit Prompt" if prompt else "New Prompt")
        self.setFixedSize(540, 420)
        self.setStyleSheet("""
            QDialog {
                background-color: #171723;
                color: #f8fafc;
            }
            QLabel {
                color: #cbd5e1;
                font-weight: 500;
            }
            QLineEdit, QTextEdit {
                background-color: #1e1e2d;
                border: 1px solid #334155;
                border-radius: 6px;
                color: #f8fafc;
                padding: 8px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        layout.addWidget(QLabel("Prompt Name:"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("e.g. Lifestyle Photography")
        if prompt:
            self.name_edit.setText(prompt.name)
        layout.addWidget(self.name_edit)

        layout.addWidget(QLabel("Prompt Content (Instructions for ChatGPT):"))
        self.content_edit = QTextEdit()
        self.content_edit.setPlaceholderText("Enter the detailed prompt describing the desired generated image style...")
        if prompt:
            self.content_edit.setPlainText(prompt.content)
        layout.addWidget(self.content_edit)

        self.enabled_chk = QCheckBox("Enabled for generation pipeline")
        self.enabled_chk.setChecked(prompt.is_enabled if prompt else True)
        self.enabled_chk.setStyleSheet("color: #cbd5e1;")
        layout.addWidget(self.enabled_chk)

        btn_box = QHBoxLayout()
        btn_box.addStretch()

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setStyleSheet("""
            QPushButton {
                background-color: #334155;
                color: #f8fafc;
                border-radius: 6px;
                padding: 8px 16px;
            }
        """)
        self.btn_cancel.clicked.connect(self.reject)
        btn_box.addWidget(self.btn_cancel)

        self.btn_save = QPushButton("Save Prompt")
        self.btn_save.setStyleSheet("""
            QPushButton {
                background-color: #6366f1;
                color: #ffffff;
                font-weight: bold;
                border-radius: 6px;
                padding: 8px 20px;
            }
        """)
        self.btn_save.clicked.connect(self._validate_and_accept)
        btn_box.addWidget(self.btn_save)

        layout.addLayout(btn_box)

    def _validate_and_accept(self) -> None:
        name = self.name_edit.text().strip()
        content = self.content_edit.toPlainText().strip()
        if not name:
            QMessageBox.warning(self, "Validation Error", "Prompt name cannot be empty.")
            return
        if not content:
            QMessageBox.warning(self, "Validation Error", "Prompt content cannot be empty.")
            return
        self.accept()

    def get_data(self) -> tuple[str, str, bool]:
        return (
            self.name_edit.text().strip(),
            self.content_edit.toPlainText().strip(),
            self.enabled_chk.isChecked(),
        )


class PromptManagerPanel(QWidget):
    """Prompt Library panel managing reusable prompts with full CRUD and reordering."""

    def __init__(self):
        super().__init__()
        self._init_ui()
        self.load_prompts_from_db()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(16)

        # Header
        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("Prompt Library")
        title.setStyleSheet("font-size: 26px; font-weight: bold; color: #f8fafc;")
        subtitle = QLabel("Create, edit, duplicate, and arrange execution order of generation prompts.")
        subtitle.setStyleSheet("color: #94a3b8; font-size: 13px;")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header.addLayout(title_box)

        header.addStretch()

        # Action Buttons
        self.btn_add = QPushButton("Add Prompt")
        self.btn_add.setStyleSheet("""
            QPushButton {
                background-color: #6366f1;
                color: #ffffff;
                font-weight: bold;
                border-radius: 6px;
                padding: 10px 18px;
            }
            QPushButton:hover { background-color: #4f46e5; }
        """)
        self.btn_add.clicked.connect(self._add_prompt)
        header.addWidget(self.btn_add)

        self.btn_edit = QPushButton("Edit")
        self.btn_edit.setStyleSheet("""
            QPushButton {
                background-color: #334155;
                color: #f1f5f9;
                border-radius: 6px;
                padding: 10px 16px;
            }
            QPushButton:hover { background-color: #475569; }
        """)
        self.btn_edit.clicked.connect(self._edit_selected)
        header.addWidget(self.btn_edit)

        self.btn_duplicate = QPushButton("Duplicate")
        self.btn_duplicate.setStyleSheet("""
            QPushButton {
                background-color: #334155;
                color: #f1f5f9;
                border-radius: 6px;
                padding: 10px 16px;
            }
            QPushButton:hover { background-color: #475569; }
        """)
        self.btn_duplicate.clicked.connect(self._duplicate_selected)
        header.addWidget(self.btn_duplicate)

        self.btn_up = QPushButton("Move Up")
        self.btn_up.setStyleSheet("""
            QPushButton {
                background-color: #1e293b;
                color: #cbd5e1;
                border: 1px solid #475569;
                border-radius: 6px;
                padding: 10px 14px;
            }
        """)
        self.btn_up.clicked.connect(lambda: self._move_order(-1))
        header.addWidget(self.btn_up)

        self.btn_down = QPushButton("Move Down")
        self.btn_down.setStyleSheet("""
            QPushButton {
                background-color: #1e293b;
                color: #cbd5e1;
                border: 1px solid #475569;
                border-radius: 6px;
                padding: 10px 14px;
            }
        """)
        self.btn_down.clicked.connect(lambda: self._move_order(1))
        header.addWidget(self.btn_down)

        self.btn_delete = QPushButton("Delete")
        self.btn_delete.setStyleSheet("""
            QPushButton {
                background-color: #dc2626;
                color: #ffffff;
                border-radius: 6px;
                padding: 10px 16px;
            }
            QPushButton:hover { background-color: #b91c1c; }
        """)
        self.btn_delete.clicked.connect(self._delete_selected)
        header.addWidget(self.btn_delete)

        layout.addLayout(header)

        # Prompts Table
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels([
            "Order", "Enabled", "Prompt Name", "Prompt Content", "Created At", "Updated At"
        ])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
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
        self.table.cellDoubleClicked.connect(lambda r, c: self._edit_selected())
        layout.addWidget(self.table)

    def load_prompts_from_db(self) -> None:
        prompts = db.get_all_prompts()
        self.table.setRowCount(len(prompts))

        for row_idx, p in enumerate(prompts):
            # Order
            order_item = QTableWidgetItem(str(p.execution_order))
            order_item.setTextAlignment(Qt.AlignCenter)
            order_item.setData(Qt.UserRole, p.id)
            self.table.setItem(row_idx, 0, order_item)

            # Enabled checkbox widget
            chk = QCheckBox()
            chk.setChecked(p.is_enabled)
            chk.setStyleSheet("margin-left: 14px;")
            chk.stateChanged.connect(lambda state, prompt_id=p.id, item=p: self._toggle_enabled(prompt_id, item, state))
            self.table.setCellWidget(row_idx, 1, chk)

            # Name
            name_item = QTableWidgetItem(p.name)
            self.table.setItem(row_idx, 2, name_item)

            # Content preview
            content_item = QTableWidgetItem(p.content)
            self.table.setItem(row_idx, 3, content_item)

            # Timestamps
            created_str = p.created_at[:19].replace("T", " ") if p.created_at else ""
            updated_str = p.updated_at[:19].replace("T", " ") if p.updated_at else ""
            self.table.setItem(row_idx, 4, QTableWidgetItem(created_str))
            self.table.setItem(row_idx, 5, QTableWidgetItem(updated_str))

            self.table.setRowHeight(row_idx, 44)

    def _get_selected_prompt(self) -> PromptItem | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        order_item = self.table.item(row, 0)
        if not order_item:
            return None
        prompt_id = order_item.data(Qt.UserRole)
        all_prompts = db.get_all_prompts()
        for p in all_prompts:
            if p.id == prompt_id:
                return p
        return None

    def _toggle_enabled(self, prompt_id: int, prompt: PromptItem, state: int) -> None:
        prompt.is_enabled = (state == Qt.Checked.value or state == 2)
        prompt.updated_at = datetime.now().isoformat()
        db.update_prompt(prompt)
        signals.prompts_updated.emit()

    def _add_prompt(self) -> None:
        dlg = PromptDialog(self)
        if dlg.exec() == QDialog.Accepted:
            name, content, enabled = dlg.get_data()
            current_prompts = db.get_all_prompts()
            next_order = len(current_prompts) + 1
            new_item = PromptItem(
                id=None,
                name=name,
                content=content,
                is_enabled=enabled,
                execution_order=next_order,
            )
            db.insert_prompt(new_item)
            self.load_prompts_from_db()
            signals.prompts_updated.emit()
            signals.status_message.emit(f"Prompt '{name}' created.", 3000)

    def _edit_selected(self) -> None:
        prompt = self._get_selected_prompt()
        if not prompt:
            QMessageBox.information(self, "Select Prompt", "Please select a prompt to edit.")
            return

        dlg = PromptDialog(self, prompt=prompt)
        if dlg.exec() == QDialog.Accepted:
            name, content, enabled = dlg.get_data()
            prompt.name = name
            prompt.content = content
            prompt.is_enabled = enabled
            prompt.updated_at = datetime.now().isoformat()
            db.update_prompt(prompt)
            self.load_prompts_from_db()
            signals.prompts_updated.emit()
            signals.status_message.emit(f"Prompt '{name}' updated.", 3000)

    def _duplicate_selected(self) -> None:
        prompt = self._get_selected_prompt()
        if not prompt:
            return

        current_prompts = db.get_all_prompts()
        new_item = PromptItem(
            id=None,
            name=f"{prompt.name} (Copy)",
            content=prompt.content,
            is_enabled=prompt.is_enabled,
            execution_order=len(current_prompts) + 1,
        )
        db.insert_prompt(new_item)
        self.load_prompts_from_db()
        signals.prompts_updated.emit()
        signals.status_message.emit(f"Prompt '{new_item.name}' duplicated.", 3000)

    def _move_order(self, delta: int) -> None:
        row = self.table.currentRow()
        if row < 0:
            return

        prompts = db.get_all_prompts()
        target_idx = row + delta
        if 0 <= target_idx < len(prompts):
            p1 = prompts[row]
            p2 = prompts[target_idx]

            # Swap orders
            p1.execution_order, p2.execution_order = p2.execution_order, p1.execution_order
            p1.updated_at = datetime.now().isoformat()
            p2.updated_at = datetime.now().isoformat()
            db.update_prompt(p1)
            db.update_prompt(p2)

            self.load_prompts_from_db()
            self.table.selectRow(target_idx)
            signals.prompts_updated.emit()

    def _delete_selected(self) -> None:
        prompt = self._get_selected_prompt()
        if not prompt:
            return

        if QMessageBox.question(
            self, "Confirm Delete", f"Are you sure you want to delete prompt '{prompt.name}'?"
        ) == QMessageBox.Yes:
            db.delete_prompt(prompt.id)  # type: ignore
            self.load_prompts_from_db()
            signals.prompts_updated.emit()
            signals.status_message.emit(f"Prompt '{prompt.name}' deleted.", 3000)
