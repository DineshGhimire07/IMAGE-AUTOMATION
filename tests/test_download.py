"""Unit tests for asynchronous download queue and workers."""
import asyncio
import tempfile
from pathlib import Path
from PIL import Image
import pytest
from app.browser.download_manager import DownloadManager, DownloadTask
from app.storage.file_manager import FileManager


@pytest.mark.asyncio
async def test_download_worker_pipeline():
    """Verify that download queue workers process tasks, validate images, and invoke success callbacks."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        product_folder = tmp_path / "Product_001_Test"
        product_folder.mkdir(parents=True, exist_ok=True)

        # Create a mock valid image bytes to simulate downloaded payload
        test_img_path = tmp_path / "source.png"
        img = Image.new("RGB", (256, 256), color="red")
        img.save(test_img_path)
        valid_bytes = test_img_path.read_bytes()

        # Mock page context returning valid image bytes
        class MockResponse:
            status = 200
            async def body(self):
                return valid_bytes

        class MockRequestContext:
            async def get(self, url, timeout=30000):
                return MockResponse()

        class MockBrowserContext:
            request = MockRequestContext()

        class MockPage:
            context = MockBrowserContext()

        dm = DownloadManager(num_workers=1)
        loop = asyncio.get_running_loop()
        dm.start(loop)

        success_results = []
        failure_results = []

        async def on_success(job_id, final_path, meta):
            success_results.append((job_id, final_path, meta))

        async def on_failure(job_id, err):
            failure_results.append((job_id, err))

        dm.on_success = on_success
        dm.on_failure = on_failure

        task = DownloadTask(
            job_id=999,
            batch_folder=product_folder,
            image_index=1,
            prompt_order=1,
            prompt_name="Test Prompt",
            source_type="image_url",
            image_url="https://mock.openai.com/image.png",
            context_page=MockPage(),
        )

        await dm.enqueue(task)

        # Wait for queue processing to finish
        await asyncio.wait_for(dm.queue.join(), timeout=5.0)
        await dm.stop()

        assert len(success_results) == 1
        assert len(failure_results) == 0
        job_id, saved_path, meta = success_results[0]
        assert job_id == 999
        assert saved_path.exists()
        assert saved_path.name == "Prompt 1.png"
        assert meta["width"] == 256
        assert meta["height"] == 256


@pytest.mark.asyncio
async def test_download_via_playwright_download_event():
    """Verify that download queue works with native Playwright download event object."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        product_folder = tmp_path / "Product_002_DL"
        product_folder.mkdir(parents=True, exist_ok=True)

        # Create a mock valid WEBP image bytes
        test_img_path = tmp_path / "source.webp"
        img = Image.new("RGB", (512, 512), color="green")
        img.save(test_img_path, format="WEBP")
        webp_bytes = test_img_path.read_bytes()

        class MockPlaywrightDownload:
            suggested_filename = "generated_editorial.webp"
            async def save_as(self, path):
                Path(path).write_bytes(webp_bytes)

        dm = DownloadManager(num_workers=1)
        loop = asyncio.get_running_loop()
        dm.start(loop)

        success_results = []
        async def on_success(job_id, final_path, meta):
            success_results.append((job_id, final_path, meta))

        dm.on_success = on_success

        task = DownloadTask(
            job_id=1001,
            batch_folder=product_folder,
            image_index=2,
            prompt_order=2,
            prompt_name="Editorial Shoot",
            source_type="playwright_download",
            download_obj=MockPlaywrightDownload(),
        )

        await dm.enqueue(task)
        await asyncio.wait_for(dm.queue.join(), timeout=5.0)
        await dm.stop()

        assert len(success_results) == 1
        job_id, saved_path, meta = success_results[0]
        assert job_id == 1001
        assert saved_path.exists()
        assert saved_path.name == "Prompt 2.webp"
        assert saved_path.suffix == ".webp"
        assert meta["width"] == 512
        assert meta["height"] == 512
        assert meta["detected_format"] == "WEBP"
        assert "download_duration" in meta
        assert "validation_duration" in meta


@pytest.mark.asyncio
async def test_download_markdown_task():
    """Verify that download queue processes generated markdown text and saves Prompt 3.md."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        batch_folder = tmp_path / "Batch 1 - 2026-11-23"
        batch_folder.mkdir(parents=True, exist_ok=True)

        dm = DownloadManager(num_workers=1)
        loop = asyncio.get_running_loop()
        dm.start(loop)

        success_results = []
        async def on_success(job_id, final_path, meta):
            success_results.append((job_id, final_path, meta))

        dm.on_success = on_success

        md_text = "# Product Title\n\n- Bullet 1: 100% Cotton\n- Bullet 2: Premium Fit\n\nDescription goes here."

        task = DownloadTask(
            job_id=2001,
            batch_folder=batch_folder,
            image_index=1,
            prompt_order=3,
            prompt_name="Listing Description",
            source_type="markdown_text",
            markdown_content=md_text,
        )

        await dm.enqueue(task)
        await asyncio.wait_for(dm.queue.join(), timeout=5.0)
        await dm.stop()

        assert len(success_results) == 1
        job_id, saved_path, meta = success_results[0]
        assert job_id == 2001
        assert saved_path.exists()
        assert saved_path.name == "Prompt 3.md"
        assert saved_path.parent.name == "Product 01"
        assert meta["detected_format"] == "MD"
        assert meta["file_size"] > 0

        # Verify no Product 01.md alias is created (only Prompt 3.md exists)
        alias_file = saved_path.parent / "Product 01.md"
        assert not alias_file.exists()
