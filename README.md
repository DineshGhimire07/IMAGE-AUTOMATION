# XINVORA AI STUDIO

**XINVORA AI Studio** is a desktop application built with Python and PySide6 that automates repetitive AI image generation through a dedicated persistent Chrome/ChatGPT session using Playwright.

---

## Stage 1 Highlights & Architecture

- **Dedicated Chrome Profile**: Uses Playwright's persistent browser context (`browser_profile/`) to retain manual ChatGPT login sessions without storing user credentials or session secrets in databases.
- **Asynchronous Download Queue**: Decoupled browser automation from disk I/O with 2 background saving workers using temporary `.part` files, strict Pillow image integrity validation, and atomic file renaming.
- **Persistent SQLite Database**: Stores images, prompts, jobs, outputs, and system settings, with automatic recovery of interrupted jobs on startup.
- **Non-Blocking UI**: PySide6 GUI runs on the main thread while Playwright and download workers run on a dedicated background `QThread` with an `asyncio` event loop.
- **Organized Storage Hierarchy**: Generates clean folder structures:
  ```
  output_images/
  ├── Product_001_Shoe/
  │   ├── Original/
  │   │   └── Shoe.png
  │   ├── Prompt_01_Lifestyle.png
  │   └── Prompt_02_Macro_Detail.png
  ```

---

## System Requirements

- **Operating System**: Windows 10/11 (or macOS / Linux).
- **Python**: Python 3.10 - 3.13 (64-bit recommended).
- **Disk Space**: ~600 MB for PySide6 and bundled Chromium browser.

---

## Installation & Setup

### 1. Create Virtual Environment

**On Windows:**
```cmd
python -m venv .venv
.venv\Scripts\activate
```

**On macOS / Linux:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Install Playwright Chromium

```bash
python -m playwright install chromium
```

---

## Application Startup

### Quick Launch
- **Windows**: Double-click `run.bat` or run:
  ```cmd
  run.bat
  ```
- **macOS / Linux**:
  ```bash
  chmod +x run.sh
  ./run.sh
  ```

### Manual Command
```bash
python main.py
```

---

## User Workflow Guide

### Step 1: Chrome & ChatGPT Connection
1. In the left navigation, click **Chrome Connection**.
2. Click **1. Launch Browser** to open the dedicated Chrome window.
3. Click **2. Open ChatGPT** (navigates to `https://chatgpt.com`).
4. Log into your ChatGPT account manually. Your cookies and session are automatically preserved in `browser_profile/` across app restarts.
5. Click **Test Connection & Readiness** to confirm ChatGPT composer readiness.

### Step 2: Upload Images
1. Click **Image Manager** in the sidebar.
2. Click **Select Images...** or drag-and-drop image files (JPG, JPEG, PNG, WEBP).
3. The interface displays thumbnails, dimensions, file size, and SHA-256 checksums while preventing duplicate uploads.

### Step 3: Configure Prompts
1. Click **Prompt Library** in the sidebar.
2. Click **Add Prompt** to create reusable prompts (e.g. *Prompt 1: Lifestyle product shoot*, *Prompt 2: Macro detail photography*).
3. Adjust execution order using **Move Up** / **Move Down** buttons.

### Step 4: Build & Run Processing Queue
1. Click **Processing Queue** in the sidebar.
2. Click **Build Queue Matrix** (creates the combination of all uploaded images × enabled prompts).
3. Click **Start Processing**.
4. The application sequentially uploads each image, submits the corresponding prompt, monitors generation, downloads via background workers, verifies image integrity with Pillow, and updates progress in real time.

### Step 5: View Generated Outputs
1. Click **Generated Images** in the sidebar to browse verified outputs with thumbnails.
2. Double-click any row or click **Open Outputs Folder** to view organized output directories.

---

## Project Structure

```
xinvora_ai_studio/
├── main.py                     # Application startup entry point
├── requirements.txt            # Frozen dependency versions
├── README.md                   # Complete documentation
├── run.bat                     # Windows startup script
├── run.sh                      # Unix startup script
├── .gitignore                  # Git exclusions
│
├── app/
│   ├── __init__.py
│   ├── config.py               # Paths, timeouts, directory initialization
│   ├── database.py             # SQLite thread-safe CRUD & recovery
│   ├── models.py               # ImageItem, PromptItem, JobItem, OutputItem
│   │
│   ├── ui/
│   │   ├── main_window.py      # Main window & left sidebar navigation
│   │   ├── dashboard.py        # Real-time metrics & global controls
│   │   ├── image_manager.py    # Multi-file drag & drop, thumbnails
│   │   ├── prompt_manager.py   # CRUD, execution ordering, enable/disable
│   │   ├── browser_panel.py    # Dedicated profile launch & ChatGPT check
│   │   ├── queue_panel.py      # Persistent queue table & matrix builder
│   │   ├── generated_images.py # Output gallery & directory open
│   │   └── settings_panel.py   # Config persistence (output dir, timeouts)
│   │
│   ├── browser/
│   │   ├── browser_manager.py  # Playwright persistent context manager
│   │   ├── chatgpt_controller.py # ChatGPT composer, upload & generation detector
│   │   ├── page_detector.py    # Accessible ARIA resilient selectors
│   │   └── download_manager.py # Async download queue, .part files, Pillow check
│   │
│   ├── automation/
│   │   ├── job_queue.py        # Queue lifecycle & state coordinator
│   │   ├── image_processor.py  # Sequential generation worker
│   │   └── task_manager.py     # Background QThread hosting asyncio loop
│   │
│   ├── storage/
│   │   ├── file_manager.py     # Product folders & atomic renaming
│   │   └── image_validator.py  # Pillow format, size & corruption checks
│   │
│   └── utils/
│       ├── logger.py           # Rotating file & console logger
│       └── signals.py          # Decoupled Qt signal bus
│
├── data/                       # SQLite database (xinvora.db)
├── browser_profile/            # Dedicated Chrome user profile directory
├── input_images/               # Local input image storage
├── output_images/              # Structured product outputs
├── logs/                       # Rotating application log files
└── tests/                      # Automated pytest suite
    ├── test_database.py
    ├── test_storage.py
    ├── test_queue.py
    └── test_download.py
```

---

## Automated Tests

Run the test suite:
```bash
PYTHONPATH=. pytest tests/ -v
```

All 12 tests cover:
- Database table creation & migrations
- Prompt CRUD & execution reordering
- Image import & SHA-256 duplicate detection
- In-flight interrupted job restart recovery
- Queue matrix generation (Images × Prompts)
- Job status lifecycle (PENDING → UPLOADING → GENERATING → DOWNLOADING → VERIFYING → COMPLETED)
- Corrupt and invalid file rejection
- Output folder structure and atomic move
- Download queue worker verification and Pillow checks
