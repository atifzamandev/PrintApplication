# Software Requirements Specification — PDF Print Manager

**Target:** Debian-based Linux  
**Language:** Python 3.11+  
**Desktop framework:** PySide6 / Qt 6  
**Printing system:** CUPS

## 1. Purpose

PDF Print Manager is a desktop application for reliably printing PDF documents with controlled timing and sequencing.

It supports:

1. **Document Repeat Mode** — print the complete PDF repeatedly.
2. **Page-by-Page Mode** — print each PDF page as a separate job.
3. Pause, resume, cancel, progress, and logging.
4. Default/manual delays between print jobs.
5. Automatic moving of successfully printed PDFs into a `PrintedCompleted` folder.
6. A PDF split tool that creates separate one-page PDF files.

## 2. Core requirements

### 2.1 PDF selection

- Provide a **Select PDF** button.
- Use a file picker limited to `.pdf` files.
- Display the selected full file path.
- Validate that the file exists and is readable before starting.
- Disable changing the PDF, printer, mode, copy count, and delay while a print session is active.

### 2.2 Printer selection

- List CUPS printers using `lpstat -p`.
- Select the system default printer where available (`lpstat -d`).
- Provide a **Refresh Printers** button.
- Block printing if no valid printer is selected.
- Report unavailable, disabled, or rejected printers clearly.

### 2.3 Delay

- Default delay: **10 seconds**.
- User can manually set delay in seconds.
- Valid range: `0` to `86400` seconds.
- `0` means submit the next item immediately after the preceding job completes.
- Save the user’s delay preference with `QSettings`.
- During a wait, show a countdown.
- Pausing during a delay must preserve the remaining time.

## 3. Printing modes

### 3.1 Document Repeat Mode

This mode prints the entire selected PDF a configured number of times.

Workflow:

1. User selects PDF, printer, copies, and delay.
2. App submits the PDF using CUPS.
3. App captures the returned CUPS job ID.
4. App waits until that specific job completes.
5. App waits the configured delay.
6. App submits the next copy.
7. After every requested copy finishes successfully, the source PDF is archived.

Required controls:

- Radio button: **Repeat full document**
- Copies spin box, minimum `1`, default `1`
- Delay between copies field, default `10`

The implementation must submit one CUPS job per copy. Do not use `lp -n`, because the app must control the delay between copies.

Example submission:

```python
subprocess.run(
    ["lp", "-d", printer_name, str(pdf_path)],
    capture_output=True,
    text=True,
    check=False,
)
```

### 3.2 Page-by-Page Mode

This mode prints one page at a time.

Workflow:

1. Create a unique temporary session directory.
2. Split the selected PDF into individual page PDFs using `pdfseparate`.
3. Sort pages numerically.
4. Submit Page 1.
5. Wait for its CUPS job to finish.
6. Wait the configured delay.
7. Submit Page 2.
8. Continue until all pages are complete.
9. Clean temporary files.
10. Archive the original source PDF only after all pages succeed.

Required controls:

- Radio button: **Print page by page**
- Delay between pages field, default `10`
- Progress label such as `Page 7 of 30`

Temporary files must never use a fixed shared folder such as `/tmp/pdf_pages`. Use `tempfile.TemporaryDirectory()`.

Example split command:

```python
pdfseparate source.pdf /tmp/session/Page_%d.pdf
```

The normal approach should submit page PDFs directly. `pdftops` may be implemented as an optional printer-compatibility fallback.

## 4. Pause, resume, and cancel

### 4.1 Pause

- Pause prevents the app from submitting the next print job.
- If a CUPS job was already submitted, it may continue printing; the app must not falsely claim that the physical printer has stopped.
- The app should show either:
  - `Paused — current printer job is completing`
  - `Paused — waiting to submit next item`
- If paused during a delay, preserve the remaining delay.

### 4.2 Resume

- Resume continues the same session.
- It must continue from the next pending page/copy.
- It must not resubmit a job already accepted by CUPS.
- A paused countdown resumes from its remaining duration.

### 4.3 Cancel

When cancel is clicked, show a confirmation dialog with:

1. **Stop after current job**  
   Let the current submitted CUPS job finish, but submit nothing else.

2. **Cancel current printer job**  
   Run:

```bash
cancel <job-id>
```

Then stop the workflow.

Rules:

- Cancelled jobs must not move the original PDF into `PrintedCompleted`.
- Failed jobs must not move the original PDF.
- Cancel must clean only app-owned temporary files.
- The UI must return to a usable state after cancellation.

## 5. CUPS job monitoring

Use CUPS commands:

```bash
lp
lpstat
cancel
```

Required behavior:

- Capture the job ID from `lp` output, for example:

```text
request id is HP-LaserJet-1022-42 (1 file(s))
```

- Poll job state approximately once per second.
- Use `lpstat -W not-completed` and, where possible, a job-specific CUPS query.
- Monitor the exact submitted job ID.
- Do not assume that an empty queue means success.
- Record completed, failed, stopped, cancelled, aborted, and timeout states.
- Recommended timeout: 30 minutes per print item, configurable in Preferences.

Command execution requirements:

- Use argument lists with `subprocess`.
- Never use `shell=True`.
- Never interpolate paths into shell strings.
- Log return code, stdout, and stderr for diagnostics.

## 6. Completed PDF archive behavior

After a print session is fully successful:

1. Find the source PDF’s containing folder.
2. Create a sibling child folder named exactly `PrintedCompleted`.
3. Move the original PDF into it.

Example:

```text
/home/user/Downloads/Invoice.pdf
```

becomes:

```text
/home/user/Downloads/PrintedCompleted/Invoice.pdf
```

Rules:

- Archive only when every requested page/copy completed successfully.
- Default setting: **Move successfully printed PDF to PrintedCompleted** enabled.
- Save this preference with `QSettings`.
- Never overwrite an existing file.

If this exists:

```text
PrintedCompleted/Invoice.pdf
```

move the file as:

```text
PrintedCompleted/Invoice (1).pdf
```

then increment as needed.

If printing succeeds but moving fails:

- Mark the session as `Completed with archive warning`.
- Keep the source PDF in its original location.
- Show the error and provide an **Open Folder** action.

Before moving, verify that the source still exists and has not changed since the print session started.

## 7. PDF split tool

Add this menu item:

```text
Tools → Split PDF into Pages…
```

Workflow:

1. User selects a PDF.
2. Create a sibling folder named `<filename>_split`.
3. Split the PDF into one-page files.
4. Name files:

```text
Page_1.pdf
Page_2.pdf
Page_3.pdf
...
```

Example:

```text
/home/user/Documents/AI article.pdf
```

creates:

```text
/home/user/Documents/AI article_split/
├── Page_1.pdf
├── Page_2.pdf
├── Page_3.pdf
└── ...
```

Rules:

- Do not alter or move the original PDF.
- Preserve readable filename stems where possible.
- Normalize invalid path characters to `_`.
- If a populated split folder already exists, ask the user to choose:
  - Replace generated `Page_*.pdf` files
  - Create a unique folder such as `AI article_split (1)`
  - Cancel
- Never silently overwrite files.
- Create pages in a temporary folder first, then move them into the output folder only after successful splitting.
- Show the number of generated pages and offer **Open Folder**.

## 8. User interface

Use a single-window PySide6 application.

```text
┌──────────────────── PDF Print Manager ─────────────────────┐
│ File: [ /path/to/document.pdf                    ] [Select]│
│ Printer: [ HP LaserJet 1022 ▼ ] [Refresh]                  │
│                                                             │
│ Printing mode                                               │
│ (•) Repeat full document   Copies: [ 1 ]                   │
│ ( ) Print page by page                                      │
│ Delay between jobs/pages: [ 10 ] seconds                   │
│ [✓] Move completed PDF to PrintedCompleted                 │
│                                                             │
│ Status: Ready                                               │
│ Progress: [████████░░░░░░░░░░] 2 of 5 copies               │
│ Current CUPS job: HP-LaserJet-1022-42                      │
│                                                             │
│ [Start Printing] [Pause] [Resume] [Cancel] [Open Folder]  │
│                                                             │
│ Activity log                                              ▾ │
└─────────────────────────────────────────────────────────────┘
```

Menus:

- **File**
  - Select PDF
  - Open Source Folder
  - Exit

- **Tools**
  - Split PDF into Pages…
  - Refresh Printers

- **Settings**
  - Preferences…

- **Help**
  - User Guide
  - About
  - View Log Folder

Control states:

| State | Start | Pause | Resume | Cancel | Edit settings |
|---|---:|---:|---:|---:|---:|
| Ready | Yes | No | No | No | Yes |
| Running | No | Yes | No | Yes | No |
| Paused | No | No | Yes | Yes | No |
| Cancelling | No | No | No | Yes | No |
| Finished / Failed / Cancelled | Yes | No | No | No | Yes |

Accessibility requirements:

- Visible labels for every field.
- Complete keyboard navigation.
- Do not rely on colour alone for status.
- Use accessible names/tooltips for controls.

## 9. Architecture

Use a layered design.

```text
PySide6 UI
    ↓ signals and immutable state updates
JobManager / Print Session State Machine
    ↓
CupsClient, PdfService, ArchiveService, SettingsService
    ↓
subprocess, filesystem, QSettings, logging
```

### Components

| Component | Responsibility |
|---|---|
| `MainWindow` | User interface and status rendering. |
| `JobManager` | Session lifecycle and legal state transitions. |
| `PrintWorker` | Long-running printing work outside the UI thread. |
| `CupsClient` | Printer listing, job submission, monitoring, cancellation. |
| `PdfService` | Validation and page splitting. |
| `ArchiveService` | Collision-safe `PrintedCompleted` move. |
| `SettingsService` | QSettings preferences. |
| `SessionLogger` | Activity log and rotating log files. |
| `models.py` | Enums, dataclasses, result models. |

### State machine

```text
IDLE
→ VALIDATING
→ PREPARING
→ SUBMITTING
→ WAITING_FOR_CUPS
→ WAITING_DELAY
→ ARCHIVING
→ COMPLETED / COMPLETED_WITH_WARNING

Active state → PAUSED → prior checkpoint
Active state → CANCELLING → CANCELLED
Active state → FAILED
```

Use an explicit state enum. Keep all transitions centralized in `JobManager`.

### Threading

- The Qt main thread must only handle UI.
- Move `PrintWorker` to a `QThread`, or use an equivalent controlled worker.
- Workers communicate through Qt signals.
- Never update widgets directly from worker code.
- Use events/conditions for pause and cancellation.
- Do not use `QThread.terminate()`.

## 10. Technical dependencies

System packages:

```bash
sudo apt install cups cups-client poppler-utils
```

Python dependency:

```text
PySide6>=6.6
```

System commands required:

```text
lp
lpstat
cancel
pdfseparate
pdftops
```

`pdfseparate` and `pdftops` come from `poppler-utils`.

## 11. Recommended project structure

```text
pdf-print-manager/
├── pyproject.toml
├── README.md
├── requirements-dev.txt
├── assets/
│   ├── icons/
│   └── pdf-print-manager.desktop
├── src/
│   └── pdf_print_manager/
│       ├── __init__.py
│       ├── __main__.py
│       ├── app.py
│       ├── config.py
│       ├── models.py
│       ├── job_manager.py
│       ├── worker.py
│       ├── services/
│       │   ├── cups_client.py
│       │   ├── pdf_service.py
│       │   ├── archive_service.py
│       │   ├── settings_service.py
│       │   └── logging_service.py
│       └── ui/
│           ├── main_window.py
│           ├── print_settings_panel.py
│           ├── progress_panel.py
│           ├── log_panel.py
│           ├── split_dialog.py
│           └── preferences_dialog.py
└── tests/
    ├── unit/
    └── integration/
```

## 12. Suggested models

```python
class PrintMode(Enum):
    DOCUMENT_REPEAT = "document_repeat"
    PAGE_BY_PAGE = "page_by_page"


class SessionState(Enum):
    IDLE = auto()
    VALIDATING = auto()
    PREPARING = auto()
    SUBMITTING = auto()
    WAITING_FOR_CUPS = auto()
    WAITING_DELAY = auto()
    PAUSED = auto()
    CANCELLING = auto()
    ARCHIVING = auto()
    COMPLETED = auto()
    COMPLETED_WITH_WARNING = auto()
    CANCELLED = auto()
    FAILED = auto()


@dataclass(frozen=True)
class PrintRequest:
    source_path: Path
    printer_name: str
    mode: PrintMode
    copies: int
    delay_seconds: int
    archive_completed_pdf: bool = True
    item_timeout_seconds: int = 1800
```

## 13. Error handling

| Situation | Required behavior |
|---|---|
| Invalid/unreadable PDF | Block start and show corrective message. |
| No printer available | Block start; allow refresh. |
| Missing system command | Explain missing package/command. |
| PDF split fails | Keep source, remove temporary files, show details. |
| `lp` submission fails | Stop session and keep source. |
| CUPS job fails/cancels | Stop session and keep source. |
| Printer offline | Fail/timeout gracefully; do not archive. |
| Archive permission error | Mark completed with warning; retain source. |
| Split-folder conflict | Ask user; never overwrite silently. |
| Unexpected error | Restore responsive UI, clean session temp files, log traceback. |

## 14. Testing requirements

### Unit tests

- CUPS job-ID parsing.
- CUPS status parsing.
- Numeric page sorting.
- Archive file collision naming.
- Delay countdown pause/resume behavior.
- Cancellation preventing future submissions.
- State-machine transition validation.

### Integration tests

- Split a known multi-page PDF and verify `Page_1.pdf` through `Page_N.pdf`.
- Use a fake/injected CUPS client for repeat mode.
- Verify page-by-page submissions are sequential and numerically ordered.
- Verify successful print sessions archive source PDFs.
- Verify cancelled/failed sessions do not archive source PDFs.

## 15. Acceptance criteria

1. The app runs as a PySide6 desktop application on Debian-based Linux.
2. The user can select a valid PDF and a CUPS printer.
3. Default delay is 10 seconds and can be changed manually.
4. Repeat mode submits exactly one full-PDF job per requested copy.
5. Page-by-page mode submits exactly one CUPS job per page in numeric order.
6. The UI remains responsive during printing and delays.
7. Pause prevents future submissions and preserves remaining delay.
8. Resume continues without duplicate copies/pages.
9. Cancel stops future submissions and never archives the source PDF.
10. Successful sessions move the original PDF to `PrintedCompleted` beside its source folder.
11. Existing archive files are never overwritten.
12. Split tool creates `<filename>_split/Page_1.pdf` through `Page_N.pdf`.
13. Existing split output is never silently overwritten.
14. Printing, CUPS, filesystem, and dependency errors are shown in understandable language.
15. Core workflow, archive behavior, cancellation, page order, and split logic are covered by automated tests.

## 16. Implementation order

1. Create project scaffold, data models, and test setup.
2. Implement CUPS client and unit tests.
3. Implement PDF split and archive services with tests.
4. Implement state machine and background worker.
5. Implement pause, resume, cancel, and progress signals.
6. Build the PySide6 main window and dialogs.
7. Add settings, logging, launcher, packaging, and README.
8. Test with a fake CUPS client and then with a real CUPS printer.

## 17. Deliverables

Claude Code should produce:

- Complete Python/PySide6 application source.
- `README.md` with Debian installation, development, packaging, and troubleshooting instructions.
- Automated unit and integration tests.
- `.desktop` launcher and icon.
- Logging implementation.
- User guide explaining printing modes, delays, pause/resume/cancel, `PrintedCompleted`, and PDF splitting.