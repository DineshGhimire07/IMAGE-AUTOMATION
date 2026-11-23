"""Main entry point for XINVORA AI Studio desktop application."""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from app.config import config
from app.database import db
from app.utils.logger import logger
from app.automation.task_manager import task_manager
from app.ui.main_window import MainWindow


def main() -> int:
    """Initializes and runs XINVORA AI Studio."""
    logger.info("=========================================")
    logger.info("Starting %s v%s", config.app_name, config.version)
    logger.info("Project Root: %s", config.root_dir)
    logger.info("Python Version: %s", sys.version)
    logger.info("=========================================")

    # Ensure all directories exist
    config.ensure_directories()

    # Recover any interrupted jobs from previous application run
    recovered = db.recover_interrupted_jobs()
    if recovered > 0:
        logger.info("Restored %d interrupted jobs to PENDING state.", recovered)

    # Initialize PySide6 Application
    app = QApplication(sys.argv)
    app.setApplicationName(config.app_name)
    app.setOrganizationName("XINVORA")

    # Start the background asyncio TaskManager thread
    logger.info("Starting background TaskManager thread...")
    task_manager.start()

    # Initialize and present Main Window
    window = MainWindow()
    window.show()

    # Enter Qt main event loop
    exit_code = app.exec()

    # Cleanup background services
    logger.info("Shutting down background tasks...")
    task_manager.stop_loop()
    logger.info("Application exited with code %d", exit_code)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
