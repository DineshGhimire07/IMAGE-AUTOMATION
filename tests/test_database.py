"""Unit tests for SQLite database operations and models."""
import tempfile
from pathlib import Path
import pytest
from app.database import Database
from app.models import ImageItem, PromptItem, JobItem, JobStatus, OutputItem


@pytest.fixture
def temp_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    db = Database(db_path=db_path)
    yield db
    if db_path.exists():
        try:
            db_path.unlink()
        except OSError:
            pass


def test_database_initialization(temp_db):
    """Verify that tables are created properly."""
    with temp_db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [row["name"] for row in cursor.fetchall()]
        assert "images" in tables
        assert "prompts" in tables
        assert "jobs" in tables
        assert "outputs" in tables
        assert "settings" in tables


def test_prompt_creation_and_editing(temp_db):
    """Verify prompt CRUD operations and execution order."""
    prompt = PromptItem(
        id=None,
        name="Lifestyle Shoot",
        content="Clean lifestyle photography with natural lighting.",
        execution_order=1,
    )
    p_id = temp_db.insert_prompt(prompt)
    assert p_id is not None

    prompts = temp_db.get_all_prompts()
    assert len(prompts) == 1
    assert prompts[0].name == "Lifestyle Shoot"
    assert prompts[0].is_enabled is True

    # Edit prompt
    prompts[0].name = "Studio Macro Shoot"
    prompts[0].content = "Macro detail product close-up."
    prompts[0].is_enabled = False
    temp_db.update_prompt(prompts[0])

    updated = temp_db.get_all_prompts()
    assert updated[0].name == "Studio Macro Shoot"
    assert updated[0].is_enabled is False


def test_duplicate_image_detection(temp_db):
    """Verify duplicate detection using checksum."""
    img1 = ImageItem(
        id=None,
        original_path="/path/test1.png",
        filename="test1.png",
        width=800,
        height=600,
        file_size=1024,
        checksum="hash_123456",
    )
    id1 = temp_db.insert_image(img1)
    assert id1 is not None

    # Insert duplicate checksum
    img2 = ImageItem(
        id=None,
        original_path="/path/test2_duplicate.png",
        filename="test2_duplicate.png",
        width=800,
        height=600,
        file_size=1024,
        checksum="hash_123456",
    )
    id2 = temp_db.insert_image(img2)
    assert id2 is None  # Skipped as duplicate

    all_images = temp_db.get_all_images()
    assert len(all_images) == 1


def test_interrupted_job_recovery(temp_db):
    """Verify that in-flight jobs are safely reset to PENDING upon restart."""
    # Insert prerequisite image and prompt
    img_id = temp_db.insert_image(ImageItem(
        id=None, original_path="/img.png", filename="img.png",
        width=100, height=100, file_size=500, checksum="abc"
    ))
    prompt_id = temp_db.insert_prompt(PromptItem(
        id=None, name="Test Prompt", content="Generate"
    ))

    # Insert jobs with various statuses
    job1_id = temp_db.insert_job(JobItem(
        id=None, image_id=img_id, image_path="/img.png",
        prompt_id=prompt_id, prompt_text="Gen", status=JobStatus.UPLOADING
    ))
    job2_id = temp_db.insert_job(JobItem(
        id=None, image_id=img_id, image_path="/img.png",
        prompt_id=prompt_id, prompt_text="Gen", status=JobStatus.GENERATING
    ))
    job3_id = temp_db.insert_job(JobItem(
        id=None, image_id=img_id, image_path="/img.png",
        prompt_id=prompt_id, prompt_text="Gen", status=JobStatus.COMPLETED
    ))

    recovered = temp_db.recover_interrupted_jobs()
    assert recovered == 2

    j1 = temp_db.get_job(job1_id)
    j2 = temp_db.get_job(job2_id)
    j3 = temp_db.get_job(job3_id)

    assert j1.status == JobStatus.PENDING
    assert j2.status == JobStatus.PENDING
    assert j3.status == JobStatus.COMPLETED  # Completed job stays completed


def test_reset_jobs_to_pending_for_retry(temp_db):
    """Verify selective retry for completed or failed jobs."""
    img_id = temp_db.insert_image(ImageItem(
        id=None, original_path="/img.png", filename="img.png",
        width=100, height=100, file_size=500, checksum="abc"
    ))
    prompt_id = temp_db.insert_prompt(PromptItem(
        id=None, name="P", content="Gen"
    ))
    job1_id = temp_db.insert_job(JobItem(
        id=None, image_id=img_id, image_path="/img.png",
        prompt_id=prompt_id, prompt_text="Gen", status=JobStatus.COMPLETED,
        output_path="/out/p1.png"
    ))
    job2_id = temp_db.insert_job(JobItem(
        id=None, image_id=img_id, image_path="/img.png",
        prompt_id=prompt_id, prompt_text="Gen", status=JobStatus.FAILED,
        error_message="Click timeout"
    ))

    # Retry job1 (completed thumbnail user didn't like) and job2 (failed)
    count = temp_db.reset_jobs_to_pending([job1_id, job2_id])
    assert count == 2

    j1 = temp_db.get_job(job1_id)
    j2 = temp_db.get_job(job2_id)
    assert j1.status == JobStatus.PENDING
    assert j1.retry_count == 1
    assert j2.status == JobStatus.PENDING
    assert j2.error_message is None
    assert j2.retry_count == 1
