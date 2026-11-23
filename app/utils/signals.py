"""Qt Global Signal bus for decoupled event communication."""
from __future__ import annotations

try:
    from PySide6.QtCore import QObject, Signal
except ImportError:
    # Dummy fallback during initial environment bootstrapping if needed
    class QObject:
        pass
    def Signal(*args, **kwargs):
        class _DummySignal:
            def connect(self, *a, **k): pass
            def emit(self, *a, **k): pass
        return _DummySignal()


class AppSignals(QObject):
    """Central Qt signals for XINVORA AI Studio."""
    # Images
    images_updated = Signal()

    # Prompts
    prompts_updated = Signal()

    # Jobs / Queue
    jobs_updated = Signal()
    job_status_changed = Signal(int, str, str)  # job_id, status, error_message
    queue_state_changed = Signal(str)  # "IDLE", "RUNNING", "PAUSED", "STOPPED"
    queue_progress = Signal(int, int)  # completed, total

    # Browser
    browser_status_changed = Signal(str, str, str)  # browser_state, chatgpt_state, current_url
    browser_log = Signal(str)

    # Downloads
    download_completed = Signal(int, str)  # job_id, output_path
    download_failed = Signal(int, str)  # job_id, error_message

    # Diagnostic / System
    status_message = Signal(str, int)  # message, timeout_ms


signals = AppSignals()
