# PDF Print Manager

A PySide6 desktop app for printing PDFs on Debian-based Linux with controlled
timing and sequencing: repeat a whole document a set number of times, or
print it one page at a time, with pause/resume/cancel and an automatic
`PrintedCompleted` archive once a session finishes successfully.

Design reference: [SoftwareArchitecture.md](SoftwareArchitecture.md).

## Contents

- [Installing on Debian](#installing-on-debian)
- [Running it](#running-it)
- [Development setup](#development-setup)
- [Running the tests](#running-the-tests)
- [Packaging / desktop launcher](#packaging--desktop-launcher)
- [User guide](#user-guide)
- [Troubleshooting](#troubleshooting)

## Installing on Debian

System packages (CUPS client tools + poppler's `pdfseparate`/`pdftops`):

```bash
sudo apt update
sudo apt install cups cups-client poppler-utils python3-venv python3-pip
```

If you're printing from this machine for the first time, make sure CUPS
itself is running and at least one printer is configured (via `system-config-printer`
or `http://localhost:631`), and that your user can run `lp`/`lpstat`/`cancel`
without `sudo` (the `lpadmin` group usually covers this — `sudo usermod -aG lpadmin $USER`,
then log out and back in).

Then, from this project's folder:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install .
```

## Running it

```bash
source .venv/bin/activate
pdf-print-manager
```

or, without installing the console script:

```bash
python -m pdf_print_manager
```

## Development setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

This installs the app in editable mode (`-e .`) plus `pytest`.

## Running the tests

```bash
pytest
```

Everything under `tests/unit/` and most of `tests/integration/` runs without
touching a real printer, CUPS queue, or `pdfseparate` — printer/job behaviour
is exercised through an in-memory fake CUPS client
(`tests/conftest.py::FakeCupsClient`), and a handful of integration tests
build a real minimal multi-page PDF at test time (`tests/pdf_fixtures.py`) to
exercise the real `pdfseparate` binary.

Tests that need `pdfseparate` skip automatically (rather than fail) if
poppler-utils isn't installed — install it and re-run to include them:

```bash
sudo apt install poppler-utils
pytest -v
```

## Packaging / desktop launcher

A `.desktop` launcher and SVG icon are in `assets/`. To install them for the
current user after `pip install .`:

```bash
mkdir -p ~/.local/share/applications ~/.local/share/icons/hicolor/scalable/apps
cp assets/pdf-print-manager.desktop ~/.local/share/applications/
cp assets/icons/pdf-print-manager.svg ~/.local/share/icons/hicolor/scalable/apps/
update-desktop-database ~/.local/share/applications 2>/dev/null || true
```

The app should then show up in your desktop's application launcher as
"PDF Print Manager".

## User guide

### Printing modes

- **Repeat full document** — prints the whole PDF a set number of times
  (**Copies**). Each copy is its own CUPS job; the app waits for one copy to
  finish printing before submitting the next.
- **Print page by page** — splits the PDF into single-page files (in a
  private temporary folder, cleaned up automatically) and submits them one
  at a time, in page order.
- **Bulk print (multiple files)** — pick any number of PDFs with **Select
  Files…**; they're listed in the order they'll print. Click **Start
  Printing** and they're submitted one at a time, in that order, with the
  same delay between them as the other modes. Each file is archived to its
  own `PrintedCompleted` folder right after *it* finishes printing —
  independently of the others — so files from different folders each land
  next to where they started. A check mark appears next to each file in the
  list as it's printed; use **Remove Selected** or **Clear All** to edit the
  list before starting. If one file fails partway through, the batch stops
  there: files already printed keep their check marks and stay archived, and
  the rest are left untouched in their original location.

All three modes share a **delay** (seconds) between items — the wait starts
once CUPS reports the previous job finished, not from when it was submitted.
`0` means "submit the next item immediately."

### Pause, resume, cancel

- **Pause** stops the app from submitting anything further. A job already
  sent to the printer keeps printing — pausing controls the app's queue, not
  the physical device. If paused during the between-items delay, the
  remaining countdown is preserved and picks up exactly where it left off on
  **Resume**.
- **Cancel** asks how to stop:
  - *Stop after current job* — lets the in-flight job finish printing, then
    ends the session without submitting anything else.
  - *Cancel current printer job* — runs `cancel <job-id>` immediately, then
    ends the session.
  
  Either way, the source PDF is **not** archived, and only this session's
  own temporary files are removed.

### PrintedCompleted archive

Once every requested copy/page has printed successfully, the original PDF is
moved into a `PrintedCompleted` folder next to it — e.g.
`~/Documents/Invoice.pdf` becomes `~/Documents/PrintedCompleted/Invoice.pdf`.
An existing file of the same name is never overwritten; the app appends
` (1)`, ` (2)`, etc. If printing succeeds but the move itself fails (e.g. a
permissions problem), the session is marked "Completed with archive warning"
and the source file is left exactly where it was — use **Open Folder** to go
find it.

This behaviour can be turned off (**Move completed PDF to PrintedCompleted**,
in the main window and in Preferences).

### Splitting a PDF without printing

**Tools → Split PDF into Pages…** splits any PDF into `Page_1.pdf` …
`Page_N.pdf` inside a sibling `<name>_split` folder, without printing or
touching the original file. If that folder already has generated pages in
it, you're asked whether to replace just the generated files, create a new
numbered folder instead, or cancel — existing output is never silently
overwritten.

### Preferences

**Settings → Preferences…** sets the defaults used for new sessions: the
delay between items, how long to wait for a single job before giving up
(the *item timeout*, 30 minutes by default), whether to archive on success,
and a shortcut to the log folder.

## Troubleshooting

**"No printers found"** — run `lpstat -p` yourself to confirm CUPS sees a
printer; click **Refresh Printers** after fixing it. The app never guesses —
if a printer is disabled or not accepting jobs, it's shown as such and can't
be selected.

**A job seems stuck at "Printing… — job in progress"** — the app polls CUPS
about once a second and won't assume success just because a job disappeared
from the queue; it also checks CUPS's completed/aborted/cancelled job
history before declaring success. If a job's outcome truly can't be
confirmed, or it runs past the configured item timeout, the session ends as
**Failed** rather than silently moving on — the source file is always kept
in that case.

**Missing `pdfseparate` / `pdftops`** — install `poppler-utils`
(`sudo apt install poppler-utils`). Page-by-Page mode and the Split tool
both need `pdfseparate`; `pdftops` is only used as an optional
printer-compatibility fallback.

**Logs** — a rotating log file lives under
`~/.local/share/pdf-print-manager/logs/` (or `$XDG_STATE_HOME`/
`$XDG_DATA_HOME` if set). **Help → View Log Folder** opens it directly; every
`lp`/`lpstat`/`cancel`/`pdfseparate` call is logged with its return code,
stdout, and stderr.

## License

MIT.
