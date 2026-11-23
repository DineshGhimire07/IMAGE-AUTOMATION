"""Image validation and metadata extraction using Pillow with single-pass I/O."""
from __future__ import annotations

import io
import hashlib
from pathlib import Path
from typing import Tuple, Optional, Dict, Any
from PIL import Image
from app.utils.logger import logger

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


class ImageValidationError(Exception):
    """Raised when an image fails validation checks."""
    pass


class ImageValidator:
    """
    Validates image integrity, dimensions, size, and calculates checksums.
    Optimized for single-pass file reading into memory to eliminate repeated disk I/O.
    """

    @staticmethod
    def calculate_checksum(file_path: Path) -> str:
        """Calculate SHA-256 checksum of a file directly from disk."""
        hasher = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                hasher.update(chunk)
        return hasher.hexdigest()

    @classmethod
    def validate_markdown_file(cls, file_path: Path) -> Dict[str, Any]:
        """
        Validates that:
        1. Markdown file exists and is a regular file.
        2. Size is greater than zero.
        3. Can be decoded as UTF-8 text.

        Returns metadata dict: {width, height, format, file_size, checksum, line_count}
        """
        path = Path(file_path)
        if not path.exists():
            raise ImageValidationError(f"File does not exist: {file_path}")
        if not path.is_file():
            raise ImageValidationError(f"Path is not a regular file: {file_path}")

        file_size = path.stat().st_size
        if file_size == 0:
            raise ImageValidationError("Markdown file is empty (0 bytes).")

        try:
            content = path.read_text(encoding="utf-8")
        except Exception as e:
            raise ImageValidationError(f"Failed to decode markdown file as UTF-8: {e}") from e

        checksum = cls.calculate_checksum(path)
        return {
            "width": 0,
            "height": 0,
            "format": "MD",
            "file_size": file_size,
            "checksum": checksum,
            "line_count": len(content.splitlines()),
        }

    @classmethod
    def validate_image_file(cls, file_path: Path, allow_part: bool = False) -> Dict[str, Any]:
        """
        Validates that:
        1. File exists and is a regular file.
        2. Size is greater than zero.
        3. Extension is supported (JPG, JPEG, PNG, WEBP), or allow_part=True for temp downloads.
        4. Pillow can open and verify image integrity without corruption.
        5. Width and height are greater than zero.

        Performs a single disk read into an in-memory buffer, calculating SHA-256
        and verifying image headers without re-reading the file from disk 3 times.

        Returns metadata dict: {width, height, format, file_size, checksum}
        """
        path = Path(file_path)
        if not path.exists():
            raise ImageValidationError(f"File not found: {path}")

        if not path.is_file():
            raise ImageValidationError(f"Path is not a regular file: {path}")

        file_size = path.stat().st_size
        if file_size <= 0:
            raise ImageValidationError(f"File is empty (0 bytes): {path.name}")

        ext = path.suffix.lower()
        if not (allow_part and ext == ".part"):
            if ext not in SUPPORTED_EXTENSIONS:
                raise ImageValidationError(
                    f"Unsupported format '{ext}'. Allowed: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
                )

        try:
            # Single-pass read: read data once into memory
            data = path.read_bytes()

            # Fast in-memory SHA-256 calculation
            checksum = hashlib.sha256(data).hexdigest()

            # First pass: verify image integrity
            with Image.open(io.BytesIO(data)) as img:
                img.verify()

            # Second pass: inspect dimensions and detected format
            with Image.open(io.BytesIO(data)) as img:
                width, height = img.size
                img_format = img.format or ext.lstrip(".").upper()

            if width <= 0 or height <= 0:
                raise ImageValidationError(f"Invalid image dimensions: {width}x{height}")

            return {
                "width": width,
                "height": height,
                "format": img_format,
                "file_size": file_size,
                "checksum": checksum,
                "filename": path.name,
                "path": str(path.resolve()),
            }
        except ImageValidationError:
            raise
        except Exception as e:
            logger.error("Failed image validation on %s: %s", path, e)
            raise ImageValidationError(f"Corrupt or unreadable image file: {e}") from e

    @classmethod
    def verify_downloaded_part(cls, part_path: Path, min_dimension: int = 10) -> bool:
        """Verifies a downloaded .part file before atomic rename."""
        try:
            meta = cls.validate_image_file(part_path, allow_part=True)
            return meta["width"] >= min_dimension and meta["height"] >= min_dimension
        except Exception as e:
            logger.warning("Downloaded file failed validation: %s: %s", part_path, e)
            return False
