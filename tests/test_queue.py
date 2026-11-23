"""Unit tests for job queue transitions and matrix generation."""
import tempfile
from pathlib import Path
import pytest
from app.database import Database
from app.models import ImageItem, PromptItem, JobStatus
from app.automation.job_queue import JobQueue


@pytest.fixture
def queue_and_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    test_db = Database(db_path=db_path)

    # Monkey patch global db for JobQueue testing
    import app.automation.job_queue as jq_module
    import app.database as db_module
    old_db = jq_module.db
    jq_module.db = test_db

    q = JobQueue()
    yield q, test_db

    jq_module.db = old_db
    if db_path.exists():
        try:
            db_path.unlink()
        except OSError:
            pass


def test_queue_matrix_generation(queue_and_db):
    """Verify matrix job generation for 2 images x 2 prompts = 4 jobs."""
    q, test_db = queue_and_db

    # Insert 2 images
    img1_id = test_db.insert_image(ImageItem(
        id=None, original_path="/img1.png", filename="img1.png",
        width=500, height=500, file_size=2000, checksum="chk1"
    ))
    img2_id = test_db.insert_image(ImageItem(
        id=None, original_path="/img2.png", filename="img2.png",
        width=500, height=500, file_size=2000, checksum="chk2"
    ))

    # Insert 2 prompts
    p1_id = test_db.insert_prompt(PromptItem(
        id=None, name="Prompt 1", content="Lifestyle product photo", execution_order=1
    ))
    p2_id = test_db.insert_prompt(PromptItem(
        id=None, name="Prompt 2", content="Close-up detail photo", execution_order=2
    ))

    images = test_db.get_all_images()
    prompts = test_db.get_all_prompts()

    jobs = q.populate_jobs(images, prompts)
    assert len(jobs) == 4

    # Verify all jobs start with PENDING
    for j in jobs:
        assert j.status == JobStatus.PENDING

    # Verify execution order: prompt 1 comes before prompt 2
    assert jobs[0].prompt_id == p1_id
    assert jobs[1].prompt_id == p2_id
    assert jobs[2].prompt_id == p1_id
    assert jobs[3].prompt_id == p2_id


def test_job_status_transitions(queue_and_db):
    """Verify job status transitions from PENDING through COMPLETED and FAILED."""
    q, test_db = queue_and_db

    img_id = test_db.insert_image(ImageItem(
        id=None, original_path="/img.png", filename="img.png",
        width=100, height=100, file_size=500, checksum="chk"
    ))
    p_id = test_db.insert_prompt(PromptItem(
        id=None, name="P", content="Prompt"
    ))

    jobs = q.populate_jobs(test_db.get_all_images(), test_db.get_all_prompts())
    job_id = jobs[0].id

    # PENDING -> UPLOADING
    q.mark_job_status(job_id, JobStatus.UPLOADING)
    assert test_db.get_job(job_id).status == JobStatus.UPLOADING

    # UPLOADING -> GENERATING
    q.mark_job_status(job_id, JobStatus.GENERATING)
    assert test_db.get_job(job_id).status == JobStatus.GENERATING

    # GENERATING -> DOWNLOADING
    q.mark_job_status(job_id, JobStatus.DOWNLOADING)
    assert test_db.get_job(job_id).status == JobStatus.DOWNLOADING

    # DOWNLOADING -> VERIFYING
    q.mark_job_status(job_id, JobStatus.VERIFYING)
    assert test_db.get_job(job_id).status == JobStatus.VERIFYING

    # VERIFYING -> COMPLETED
    output_file = "/outputs/Prompt_01.png"
    q.mark_job_status(job_id, JobStatus.COMPLETED, output_path=output_file)
    j_done = test_db.get_job(job_id)
    assert j_done.status == JobStatus.COMPLETED
    assert j_done.output_path == output_file
    assert j_done.completed_at is not None
