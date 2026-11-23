"""SQLite Database layer for XINVORA AI Studio."""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import List, Optional, Dict, Any
from app.config import config
from app.models import ImageItem, PromptItem, JobItem, OutputItem, JobStatus
from app.utils.logger import logger


class Database:
    """Thread-safe SQLite database manager."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or config.db_path
        self._lock = threading.Lock()
        self.init_db()

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def init_db(self) -> None:
        """Create tables if they do not exist."""
        with self._lock, self.get_connection() as conn:
            cursor = conn.cursor()

            # Schema versioning / migrations table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER PRIMARY KEY
                );
            """)

            # Images table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS images (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    original_path TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    width INTEGER NOT NULL,
                    height INTEGER NOT NULL,
                    file_size INTEGER NOT NULL,
                    checksum TEXT UNIQUE NOT NULL,
                    created_at TEXT NOT NULL
                );
            """)

            # Prompts table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS prompts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    is_enabled INTEGER DEFAULT 1,
                    execution_order INTEGER DEFAULT 0
                );
            """)

            # Jobs table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    image_id INTEGER NOT NULL,
                    image_path TEXT NOT NULL,
                    prompt_id INTEGER NOT NULL,
                    prompt_text TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    output_path TEXT,
                    error_message TEXT,
                    retry_count INTEGER DEFAULT 0,
                    FOREIGN KEY (image_id) REFERENCES images(id) ON DELETE CASCADE,
                    FOREIGN KEY (prompt_id) REFERENCES prompts(id) ON DELETE CASCADE
                );
            """)

            # Outputs table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS outputs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id INTEGER NOT NULL,
                    image_id INTEGER NOT NULL,
                    prompt_id INTEGER NOT NULL,
                    file_path TEXT NOT NULL,
                    file_size INTEGER NOT NULL,
                    width INTEGER NOT NULL,
                    height INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
                );
            """)

            # Settings table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
            """)

            # Ensure version record
            cursor.execute("SELECT COUNT(*) FROM schema_version")
            if cursor.fetchone()[0] == 0:
                cursor.execute("INSERT INTO schema_version (version) VALUES (1)")

            conn.commit()
            logger.info("Database initialized successfully at %s", self.db_path)

    def recover_interrupted_jobs(self) -> int:
        """Restores in-flight jobs (UPLOADING, GENERATING, DOWNLOADING, VERIFYING) to PENDING."""
        with self._lock, self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE jobs
                SET status = ?, error_message = 'Interrupted by application restart'
                WHERE status IN (?, ?, ?, ?)
            """, (
                JobStatus.PENDING.value,
                JobStatus.UPLOADING.value,
                JobStatus.GENERATING.value,
                JobStatus.DOWNLOADING.value,
                JobStatus.VERIFYING.value
            ))
            recovered_count = cursor.rowcount
            conn.commit()
            if recovered_count > 0:
                logger.info("Recovered %d interrupted jobs to PENDING status.", recovered_count)
            return recovered_count

    # --- IMAGE CRUD ---
    def insert_image(self, item: ImageItem) -> Optional[int]:
        with self._lock, self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    INSERT INTO images (original_path, filename, width, height, file_size, checksum, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (item.original_path, item.filename, item.width, item.height, item.file_size, item.checksum, item.created_at))
                conn.commit()
                return cursor.lastrowid
            except sqlite3.IntegrityError:
                # Checksum already exists
                logger.debug("Duplicate image skipped: %s (checksum: %s)", item.filename, item.checksum)
                return None

    def get_image_by_checksum(self, checksum: str) -> Optional[ImageItem]:
        with self._lock, self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM images WHERE checksum = ?", (checksum,))
            row = cursor.fetchone()
            if row:
                return ImageItem(**dict(row))
            return None

    def get_all_images(self) -> List[ImageItem]:
        with self._lock, self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM images ORDER BY id ASC")
            return [ImageItem(**dict(r)) for r in cursor.fetchall()]

    def delete_image(self, image_id: int) -> bool:
        with self._lock, self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM images WHERE id = ?", (image_id,))
            conn.commit()
            return cursor.rowcount > 0

    def clear_all_images(self) -> None:
        with self._lock, self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM images")
            conn.commit()

    # --- PROMPT CRUD ---
    def insert_prompt(self, item: PromptItem) -> int:
        with self._lock, self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO prompts (name, content, created_at, updated_at, is_enabled, execution_order)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (item.name, item.content, item.created_at, item.updated_at, 1 if item.is_enabled else 0, item.execution_order))
            conn.commit()
            return cursor.lastrowid

    def update_prompt(self, item: PromptItem) -> bool:
        with self._lock, self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE prompts
                SET name = ?, content = ?, updated_at = ?, is_enabled = ?, execution_order = ?
                WHERE id = ?
            """, (item.name, item.content, item.updated_at, 1 if item.is_enabled else 0, item.execution_order, item.id))
            conn.commit()
            return cursor.rowcount > 0

    def get_all_prompts(self) -> List[PromptItem]:
        with self._lock, self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM prompts ORDER BY execution_order ASC, id ASC")
            rows = cursor.fetchall()
            return [
                PromptItem(
                    id=r["id"],
                    name=r["name"],
                    content=r["content"],
                    created_at=r["created_at"],
                    updated_at=r["updated_at"],
                    is_enabled=bool(r["is_enabled"]),
                    execution_order=r["execution_order"],
                )
                for r in rows
            ]

    def delete_prompt(self, prompt_id: int) -> bool:
        with self._lock, self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM prompts WHERE id = ?", (prompt_id,))
            conn.commit()
            return cursor.rowcount > 0

    # --- JOB CRUD ---
    def insert_job(self, item: JobItem) -> int:
        with self._lock, self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO jobs (image_id, image_path, prompt_id, prompt_text, status, created_at, started_at, completed_at, output_path, error_message, retry_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (item.image_id, item.image_path, item.prompt_id, item.prompt_text, item.status.value, item.created_at, item.started_at, item.completed_at, item.output_path, item.error_message, item.retry_count))
            conn.commit()
            return cursor.lastrowid

    def update_job_status(
        self,
        job_id: int,
        status: JobStatus,
        started_at: Optional[str] = None,
        completed_at: Optional[str] = None,
        output_path: Optional[str] = None,
        error_message: Optional[str] = None,
        increment_retry: bool = False
    ) -> None:
        with self._lock, self.get_connection() as conn:
            cursor = conn.cursor()
            query = "UPDATE jobs SET status = ?"
            params: List[Any] = [status.value]

            if started_at is not None:
                query += ", started_at = ?"
                params.append(started_at)
            if completed_at is not None:
                query += ", completed_at = ?"
                params.append(completed_at)
            if output_path is not None:
                query += ", output_path = ?"
                params.append(output_path)
            if error_message is not None:
                query += ", error_message = ?"
                params.append(error_message)
            if increment_retry:
                query += ", retry_count = retry_count + 1"

            query += " WHERE id = ?"
            params.append(job_id)
            cursor.execute(query, params)
            conn.commit()

    def get_job(self, job_id: int) -> Optional[JobItem]:
        with self._lock, self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
            row = cursor.fetchone()
            if row:
                return JobItem(**dict(row))
            return None

    def get_all_jobs(self) -> List[JobItem]:
        with self._lock, self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM jobs ORDER BY id ASC")
            return [JobItem(**dict(r)) for r in cursor.fetchall()]

    def get_pending_jobs(self) -> List[JobItem]:
        with self._lock, self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM jobs WHERE status = ? ORDER BY id ASC", (JobStatus.PENDING.value,))
            return [JobItem(**dict(r)) for r in cursor.fetchall()]

    def get_job_counts_by_status(self) -> Dict[str, int]:
        with self._lock, self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT status, COUNT(*) as cnt FROM jobs GROUP BY status")
            counts = {s.value: 0 for s in JobStatus}
            for row in cursor.fetchall():
                counts[row["status"]] = row["cnt"]
            return counts

    def clear_all_jobs(self) -> None:
        with self._lock, self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM jobs")
            conn.commit()

    def reset_jobs_to_pending(self, job_ids: List[int]) -> int:
        """Resets specified jobs (whether FAILED, COMPLETED, or INTERRUPTED) back to PENDING for retry."""
        if not job_ids:
            return 0
        with self._lock, self.get_connection() as conn:
            cursor = conn.cursor()
            placeholders = ",".join("?" for _ in job_ids)
            cursor.execute(f"""
                UPDATE jobs
                SET status = ?, error_message = NULL, started_at = NULL, completed_at = NULL, retry_count = retry_count + 1
                WHERE id IN ({placeholders})
            """, [JobStatus.PENDING.value] + job_ids)
            conn.commit()
            return cursor.rowcount

    def reset_failed_jobs(self) -> int:
        """Resets all FAILED jobs back to PENDING for retry."""
        with self._lock, self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE jobs
                SET status = ?, error_message = NULL, started_at = NULL, completed_at = NULL, retry_count = retry_count + 1
                WHERE status = ?
            """, (JobStatus.PENDING.value, JobStatus.FAILED.value))
            conn.commit()
            return cursor.rowcount

    # --- OUTPUT CRUD ---
    def insert_output(self, item: OutputItem) -> int:
        with self._lock, self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO outputs (job_id, image_id, prompt_id, file_path, file_size, width, height, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (item.job_id, item.image_id, item.prompt_id, item.file_path, item.file_size, item.width, item.height, item.created_at))
            conn.commit()
            return cursor.lastrowid

    def get_all_outputs(self) -> List[OutputItem]:
        with self._lock, self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM outputs ORDER BY id DESC")
            return [OutputItem(**dict(r)) for r in cursor.fetchall()]

    # --- SETTINGS CRUD ---
    def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        with self._lock, self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
            row = cursor.fetchone()
            return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self._lock, self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO settings (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """, (key, value))
            conn.commit()


# Global database instance
db = Database()
