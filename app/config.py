"""Application configuration and directory management."""
from __future__ import annotations

import os
from pathlib import Path
from dataclasses import dataclass, field


# Determine project root (directory containing main.py)
PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class AppConfig:
    """Central configuration for XINVORA AI Studio."""
    app_name: str = "XINVORA AI Studio"
    version: str = "1.0.0"

    # Base directories
    root_dir: Path = field(default_factory=lambda: PROJECT_ROOT)
    data_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "data")
    browser_profile_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "browser_profile")
    input_images_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "input_images")
    output_images_dir: Path = field(default_factory=lambda: Path.home() / "Desktop" / "XInvora Photos")
    logs_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "logs")

    # Database
    db_path: Path = field(default_factory=lambda: PROJECT_ROOT / "data" / "xinvora.db")

    # Browser & ChatGPT defaults
    chatgpt_url: str = "https://chatgpt.com"
    browser_type: str = "chromium"  # "chromium" or path to google-chrome
    browser_executable_path: str = ""  # empty means default playwright chromium
    headless: bool = False
    browser_slow_mo_ms: int = 50
    page_load_timeout_ms: int = 60000
    generation_timeout_seconds: int = 300    # Prompt 1 & 2 (image) timeout
    markdown_timeout_seconds: int = 600      # Prompt 3 (.md file) timeout — ChatGPT is slower
    poll_interval_seconds: float = 1.5

    # Download & Worker settings
    download_workers_count: int = 2
    max_retries_per_job: int = 2

    def ensure_directories(self) -> None:
        """Create necessary directories if they do not exist."""
        for path in [
            self.data_dir,
            self.browser_profile_dir,
            self.input_images_dir,
            self.output_images_dir,
            self.logs_dir,
        ]:
            try:
                path.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass


config = AppConfig()
config.ensure_directories()
