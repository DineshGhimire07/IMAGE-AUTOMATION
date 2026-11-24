"""File manager for organizing batch-wise photo outputs directly on the Desktop."""

from __future__ import annotations



import shutil

import re

from datetime import datetime

from pathlib import Path

from typing import Optional

from app.config import config, PROJECT_ROOT

from app.database import db

from app.utils.logger import logger





class FileManager:

    """

    Handles batch-wise folder organization on the Desktop:

    Desktop/XInvora Photos/Batch 1 - YYYY-MM-DD/Product 1 Prompt 1.png

    """



    def __init__(self, output_root: Optional[Path] = None):

        self.output_root = output_root or config.output_images_dir

        self._ensure_root_accessible()



    def _ensure_root_accessible(self) -> None:

        try:

            self.output_root.mkdir(parents=True, exist_ok=True)

        except Exception:

            self.output_root = PROJECT_ROOT / "output_images"

            try:

                self.output_root.mkdir(parents=True, exist_ok=True)

            except Exception:

                pass



    def get_or_create_batch_folder(self, force_new: bool = False) -> Path:

        """

        Returns the active batch folder.

        Preserves the same batch folder across midnight transitions (e.g. starting at 11 PM

        and finishing at 4 AM next morning stays in the same initial batch folder).

        """

        self._ensure_root_accessible()



        if not force_new:

            saved_batch = db.get_setting("current_batch_folder")

            if saved_batch:

                batch_path = Path(saved_batch)

                try:

                    if batch_path.parent == self.output_root and batch_path.exists():

                        return batch_path

                except OSError:

                    pass



        # Determine next batch number by scanning existing batch folders

        max_batch_num = 0

        batch_pattern = re.compile(r"^Batch\s+(\d+)", re.IGNORECASE)



        try:

            if self.output_root.exists():

                for folder in self.output_root.iterdir():

                    if folder.is_dir():

                        match = batch_pattern.match(folder.name)

                        if match:

                            try:

                                num = int(match.group(1))

                                if num > max_batch_num:

                                    max_batch_num = num

                            except ValueError:

                                pass

        except OSError:

            pass



        next_batch_num = max_batch_num + 1

        today_str = datetime.now().strftime("%Y-%m-%d")

        batch_folder_name = f"Batch {next_batch_num} - {today_str}"

        batch_folder = self.output_root / batch_folder_name

        try:

            batch_folder.mkdir(parents=True, exist_ok=True)

        except OSError:

            self.output_root = PROJECT_ROOT / "output_images"

            batch_folder = self.output_root / batch_folder_name

            batch_folder.mkdir(parents=True, exist_ok=True)



        # Persist as active batch

        db.set_setting("current_batch_folder", str(batch_folder.resolve()))

        logger.info("Initialized active batch folder: %s", batch_folder)

        return batch_folder



    def create_new_batch(self) -> Path:

        """Explicitly starts a new batch folder (e.g. Batch 2, Batch 3)."""

        return self.get_or_create_batch_folder(force_new=True)



    def get_product_folder(self, batch_folder: Path, image_index: int) -> Path:

        """

        Returns (and creates) the product folder inside the batch folder:

        Desktop/XInvora Photos/Batch 1 - YYYY-MM-DD/Product 01/

        Zero-pads image_index (Product 01, Product 02, etc.).

        """

        folder_name = f"Product {image_index:02d}"

        product_folder = batch_folder / folder_name

        try:

            product_folder.mkdir(parents=True, exist_ok=True)

        except OSError:

            pass

        return product_folder



    def get_output_target_path(

        self,

        batch_folder: Path,

        image_index: int,

        prompt_order: int,

        variant: Optional[str] = None,

        ext: str = ".png",

    ) -> Path:

        """

        Generates clean target path inside each product's folder:

        Desktop/XInvora Photos/Batch 1 - YYYY-MM-DD/Product 01/Prompt 1.png

        Desktop/XInvora Photos/Batch 1 - YYYY-MM-DD/Product 01/Prompt 2.png

        Desktop/XInvora Photos/Batch 1 - YYYY-MM-DD/Product 01/Prompt 3.md



        If multiple variations are generated (e.g. 2 options from ChatGPT):

        Saves as 'Prompt 1_v1.png' and 'Prompt 1_v2.png'.

        """

        if variant and variant.startswith("."):

            ext = variant

            variant = None



        if not ext.startswith("."):

            ext = f".{ext}"



        if batch_folder.name.lower().startswith("product"):

            product_folder = batch_folder

        else:

            product_folder = self.get_product_folder(batch_folder, image_index)



        variant_suffix = f"_{variant}" if variant else ""

        # .md outputs are always saved as listing.md
        if ext.lower() == ".md":
            filename = "listing.md"
        else:
            filename = f"Prompt {prompt_order}{variant_suffix}{ext}"

        return product_folder / filename



    @staticmethod

    def atomic_save_part(part_path: Path, target_path: Path, allow_overwrite: bool = True) -> Path:

        """

        Atomically moves a verified .part file to its target path.

        Overwrites existing file when retrying so remade thumbnails replace cleanly

        without creating unwanted _1, _2 duplicate tags.

        """

        target_path.parent.mkdir(parents=True, exist_ok=True)



        if not allow_overwrite and target_path.exists():

            counter = 1

            stem = target_path.stem

            suffix = target_path.suffix

            final_path = target_path

            while final_path.exists():

                final_path = target_path.parent / f"{stem}_{counter}{suffix}"

                counter += 1

        else:

            final_path = target_path



        shutil.move(str(part_path), str(final_path))

        logger.info("Successfully atomic saved %s -> %s", part_path.name, final_path)



        return final_path





file_manager = FileManager()

