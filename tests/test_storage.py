"""Unit tests for image validation, checksums, and file management."""
import tempfile
from pathlib import Path
from PIL import Image
import pytest
from app.storage.image_validator import ImageValidator, ImageValidationError
from app.storage.file_manager import FileManager


@pytest.fixture
def sample_image():
    """Generates a valid test PNG file."""
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        img_path = Path(f.name)
    img = Image.new("RGB", (320, 240), color="blue")
    img.save(img_path)
    yield img_path
    if img_path.exists():
        img_path.unlink()


def test_file_validation_valid_image(sample_image):
    """Verify validation of a valid image file."""
    meta = ImageValidator.validate_image_file(sample_image)
    assert meta["width"] == 320
    assert meta["height"] == 240
    assert meta["format"] == "PNG"
    assert meta["file_size"] > 0
    assert len(meta["checksum"]) == 64


def test_file_validation_corrupt_file():
    """Verify rejection of corrupt or invalid image files."""
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        bad_path = Path(f.name)
        bad_path.write_bytes(b"not an image file")

    try:
        with pytest.raises(ImageValidationError):
            ImageValidator.validate_image_file(bad_path)
    finally:
        if bad_path.exists():
            bad_path.unlink()


def test_file_validation_unsupported_format():
    """Verify rejection of non-image extensions."""
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
        txt_path = Path(f.name)
        txt_path.write_text("hello")

    try:
        with pytest.raises(ImageValidationError):
            ImageValidator.validate_image_file(txt_path)
    finally:
        if txt_path.exists():
            txt_path.unlink()


def test_output_naming_and_folder_structure(tmp_path):
    """Verify batch folder, Product XX subfolders, and Prompt X naming."""
    fm = FileManager(output_root=tmp_path)
    batch_folder = fm.get_or_create_batch_folder()
    assert batch_folder.name.startswith("Batch 1 - ")
    assert batch_folder.exists()

    output_path = fm.get_output_target_path(batch_folder, 1, 1, ext=".png")
    assert output_path.name == "Prompt 1.png"
    assert output_path.parent.name == "Product 01"
    assert output_path.parent.parent == batch_folder

    # Variant test (when ChatGPT generates 2 photos/options)
    output_v1 = fm.get_output_target_path(batch_folder, 1, 1, variant="v1", ext=".png")
    assert output_v1.name == "Prompt 1_v1.png"
    assert output_v1.parent.name == "Product 01"
    output_v2 = fm.get_output_target_path(batch_folder, 1, 2, variant="v2", ext=".png")
    assert output_v2.name == "Prompt 2_v2.png"

    # Markdown output for prompt 3
    output_md = fm.get_output_target_path(batch_folder, 1, 3, ext=".md")
    assert output_md.name == "Prompt 3.md"
    assert output_md.parent.name == "Product 01"

    # Next product (Product 02)
    p2_output = fm.get_output_target_path(batch_folder, 2, 1, ext=".png")
    assert p2_output.name == "Prompt 1.png"
    assert p2_output.parent.name == "Product 02"

    # Next batch
    batch_2 = fm.create_new_batch()
    assert batch_2.name.startswith("Batch 2 - ")
    assert batch_2.exists()


def test_atomic_save_part(tmp_path, sample_image):
    """Verify atomic move from .part file to target destination, including .md alias."""
    fm = FileManager(output_root=tmp_path)
    part_file = tmp_path / "temp.part"
    part_file.write_bytes(sample_image.read_bytes())

    product_dir = tmp_path / "Product 01"
    target = product_dir / "Prompt 1.png"
    final_result = fm.atomic_save_part(part_file, target)
    assert final_result.exists()
    assert final_result.name == "Prompt 1.png"

    # Test markdown atomic save and Product 01.md alias creation
    part_md = tmp_path / "temp_md.part"
    part_md.write_text("# Test Title\n- Description bullet 1", encoding="utf-8")
    target_md = product_dir / "Prompt 3.md"
    final_md = fm.atomic_save_part(part_md, target_md)
    assert final_md.exists()
    assert final_md.name == "Prompt 3.md"
    assert (product_dir / "Product 01.md").exists()
    assert (product_dir / "Product 01.md").read_text(encoding="utf-8") == "# Test Title\n- Description bullet 1"

    assert not part_file.exists()
    assert final_result.exists()
    assert final_result.stat().st_size == sample_image.stat().st_size
