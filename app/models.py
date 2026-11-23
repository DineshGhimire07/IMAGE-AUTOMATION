"""Data models for XINVORA AI Studio."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class JobStatus(str, Enum):
    PENDING = "PENDING"
    UPLOADING = "UPLOADING"
    GENERATING = "GENERATING"
    DOWNLOADING = "DOWNLOADING"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    PAUSED = "PAUSED"


@dataclass
class ImageItem:
    id: Optional[int]
    original_path: str
    filename: str
    width: int
    height: int
    file_size: int
    checksum: str
    created_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()


@dataclass
class PromptItem:
    id: Optional[int]
    name: str
    content: str
    created_at: str = ""
    updated_at: str = ""
    is_enabled: bool = True
    execution_order: int = 0

    def __post_init__(self):
        now = datetime.now().isoformat()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now


@dataclass
class JobItem:
    id: Optional[int]
    image_id: int
    image_path: str
    prompt_id: int
    prompt_text: str
    status: JobStatus = JobStatus.PENDING
    created_at: str = ""
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    output_path: Optional[str] = None
    error_message: Optional[str] = None
    retry_count: int = 0

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
        if isinstance(self.status, str):
            self.status = JobStatus(self.status)


@dataclass
class OutputItem:
    id: Optional[int]
    job_id: int
    image_id: int
    prompt_id: int
    file_path: str
    file_size: int
    width: int
    height: int
    created_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
