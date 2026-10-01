# screen-interval-capture

## What this is

Local Windows desktop app that takes a full-desktop PNG on a timer and can group those files into capture sessions. Audience is the person running it on their own machine (a time-lapse / activity record of the screen). It is a working single-file GUI, not a library and not abandoned.

Source of truth for this hand-off is the working tree, read in full (`main.py`, `test_config.py`, `README.md`, `requirements.txt`, `.gitignore`, `config.json`). Git `HEAD` is `05421a1` (`Add screen interval capture GUI with session analysis`) on `master`, tracking `origin/master` (`https://github.com/josefgoeller-ship-it/screen-interval-capture.git`). That commit matches the remote. The working tree is not the same as `HEAD`:

- `main.py` is modified. `load_config` no longer rewrites `config.json` when JSON parsing fails, and a non-numeric `interval_seconds` falls back to 60 instead of raising.
- `test_config.py` is untracked. It locks that `load_config` behavior in.

Those local changes are not committed. Reverting `main.py` to `HEAD` brings back the startup crash / config-clobber behavior the test is written against.

Not read: installed files under `.venv`, `.git` object contents, `.pytest_cache` beyond its test-node list, and the bytes of screenshots in `captures/`.

## How to run

No environment variables. Python in the project venv is 3.10.9. Runtime deps are only those in `requirements.txt`:

- `mss>=9.0.1` (venv has 10.2.0)
- `Pillow>=10.0.0` (venv has 12.3.0)

`tkinter` comes from the standard library. `pytest` is not in `requirements.txt` and is not installed in `.venv`.

Setup from `README.md` (Windows paths; the fence is labeled bash):

```bash
cd C:\MyProjects\screen-interval-capture
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

On PowerShell, activation is `.\.venv\Scripts\Activate.ps1`.

Entry point: `python main.py`, which calls `main()` and runs `ScreenIntervalApp.mainloop()`. There is no packaging config (`pyproject.toml`, `setup.cfg`, or scripts entry point).

Verified from this machine:

- `.\.venv\Scripts\python.exe -m pytest` fails: `No module named pytest`.
- System `python -m pytest -q test_config.py` (same 3.10.9) passed both tests in `test_config.py`.
- The GUI was not launched, and no screenshot was taken, during this hand-off.

`config.json` is created on first `load_config()` if it is missing (`ScreenIntervalApp.__init__` calls that). It is gitignored. The copy on disk now is:

```json
{
  "output_folder": "C:\\MyProjects\\screen-interval-capture\\captures",
  "interval_seconds": 60
}
```

`captures/` exists, is gitignored, and held 4 files when this was written. Their contents were not opened.

## Code tree

```
screen-interval-capture/
  main.py            # app, capture, config, session grouping
  test_config.py     # untracked; load_config only
  README.md
  requirements.txt
  .gitignore
  config.json        # gitignored local settings
  HANDOFF.md
```

Omitted on purpose: `.git`, `.venv`, `__pycache__`, `.pytest_cache`, and `captures/` (output images).

## Modules

Everything lives in `main.py`. There is no package.

**Config.** `CONFIG_PATH` is `config.json` next to `main.py`. `load_config()` returns a dict with `output_folder` (str) and `interval_seconds` (int). Defaults are `captures/` under the app directory and 60 seconds. `save_config()` replaces the whole file with those two keys. Callers: startup (`ScreenIntervalApp.__init__`), Start (`_start`), and window close (`_on_close`).

**Capture.** `capture_screen(folder)` makes the folder, builds a timestamp name, grabs the screen, writes a PNG, and returns the path. `unique_path()` avoids overwriting the same second by adding `_001` … `_999`, then raises `OSError`. `mss` is opened inside this function, on whatever thread calls it (the worker, once Start has run).

**Sessions.** `Session` holds `start`, `end`, and `files`. `parse_capture_time()` reads the timestamp from the filename. `group_sessions()` sorts matches and splits when the gap between filename times is greater than `interval_seconds * GAP_FACTOR` (`GAP_FACTOR` is 1.5). `format_duration()` renders seconds as `H:MM:SS`.

**GUI.** `ScreenIntervalApp` (`tk.Tk`) is the main window: folder, interval, Start, Stop, Analyze, status line. `SessionAnalysisWindow` (`tk.Toplevel`) lists sessions and the filenames in the selected one. `main()` is the process entry.

**Tests.** `test_config.py` mocks `mss` and `PIL` on `sys.modules` before importing `main`, points `CONFIG_PATH` at a temp file, and checks that an invalid `interval_seconds` does not rewrite the file. It does not open a window.

## Architecture and data flow

Start:

1. `_parse_interval()` requires a whole number of seconds, at least 1. There is no upper bound in this check (the spinbox is set from 1 to 86400, but a typed value above that still passes).
2. The folder is created. Failure is a dialog, and the thread is not started.
3. `save_config()` writes the folder and interval. The form is then locked and Start disabled.
4. A daemon thread runs `_capture_loop(folder, interval)`.
5. Each pass calls `capture_screen`: `mss.MSS().grab(monitors[0])` (the virtual desktop that spans every display), then `PIL.Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")`, saved as PNG. The name is local time `YYYY-MM-DD_HH-MM-SS.png`.
6. Status text is applied with `root.after(0, ...)` from the worker. Any exception is caught, shown in the status line, and the loop continues.
7. The thread waits the rest of the interval with `Event.wait`, so Stop can wake it. If the grab took longer than the interval, it does not wait.

Stop sets the event, unlocks the form immediately, and sets status to `Idle — stopped. Session captures: N`. When the worker actually leaves the loop it schedules `_on_worker_stopped`, which sets that Idle line only if the current status text does not already contain `"Idle"`.

Closing the window sets the event, `join`s the worker for up to 2 seconds, saves config if the interval field parses, then `destroy()`s the window.

Analyze reads the interval from the form, lists `*.png` in that folder (not subfolders), and opens `SessionAnalysisWindow` on `group_sessions(...)`. Selecting a row fills a listbox with `path.name`. Images are not decoded. A session's duration is the last filename time minus the first, so one file is `0:00:00`.

`_session_count` is an in-memory count for the current Start/Stop run. It is reset to 0 on every Start. It is not written to disk. Session analysis ignores it and uses filenames only.

## Issues and fragile spots

**`load_config` on `HEAD` is harsher than the working tree.** At `05421a1`, a `JSONDecodeError` or `OSError` calls `save_config(defaults)` and replaces the file, and `int(data.get("interval_seconds") or default)` raises `ValueError` for a string like `"not-a-number"` (uncaught, so the window never opens). `0` is also treated as missing because of `or`. The working copy avoids the rewrite and the exception. `test_config.py` covers the working copy only. Nothing in git history contains that test.

**pytest is not part of the project environment.** `requirements.txt` has no test dependency. `.venv` has no `pytest`. The two tests passed only under a system Python that already had pytest. There are no tests for `unique_path`, `capture_screen`, `group_sessions`, or the GUI.

**Stop does not wait for the in-flight grab.** `_stop` unlocks Start while `_worker` may still be inside `capture_screen`. `_start` returns immediately when that thread is alive, with no message. The worker can then queue a status string that begins with `Running —` even after Stop, and `_on_worker_stopped` uses the substring `"Idle"` to decide whether to overwrite status. That coupling is easy to break.

**Close can abandon a capture and still save.** `_on_close` joins for 2 seconds, then destroys the Tk window. The worker is a daemon. If the grab is still running, a later `after(...)` runs against a dead or dying interpreter. Not reproduced here; the timeout and the daemon flag are what make it possible.

**The “do not rewrite bad config” rule stops at `load_config`.** `_start` and `_on_close` always call `save_config`, which writes exactly two keys and has no `try`. Opening the app (bad interval is replaced in memory by 60, folder kept) and closing it overwrites the file, so the invalid value and any extra keys are lost. A corrupt JSON file is likewise replaced on close, because the form is then showing defaults and the interval parses. `save_config` will also surface `OSError` into the Tk callback with no dialog.

**`load_config` does not enforce the UI minimum.** After the working-tree change, interval `0` or a negative integer is returned as-is. Start and Analyze reject values below 1. Floats are truncated with `int()` (`60.9` becomes `60`).

**Analysis depends on the interval currently in the form.** Gaps are split at `1.5 *` that number. Files do not store the interval they were taken with. Renaming, or a slow grab whose filename gap exceeds that threshold, splits one continuous run into several sessions. Names that fail `TIMESTAMP_RE` are ignored. The dialog text is the same whether the folder has no PNGs or only non-matching names.

**The `_NNN` suffix is a collision counter, not milliseconds.** `unique_path` writes `stamp_001.png` through `stamp_999.png`. `parse_capture_time` keeps only the `YYYY-MM-DD_HH-MM-SS` group, so those files share a timestamp with the unsuffixed file. The regex is case-insensitive; the listing pattern is `*.png`. Whether `*.PNG` is included was not tested.

**README lags the app.** It describes Start and “Stop to pause”. Stop ends the loop; the next Start sets `_session_count` back to 0 and captures immediately. README does not mention Analyze, session grouping, or tests.

**Main window does not grow with the window.** `ScreenIntervalApp` grids its frame `sticky="nsew"` but never sets root row/column weights. Status `wraplength` is fixed at 440. `SessionAnalysisWindow` does set weights.

No secrets were found. `config.json` is a local folder path and an interval. No `TODO` or `FIXME` comments are in the project source.

Residual risks, not seen failing: two processes capturing the same folder can race in `unique_path` (check then create, no lock); PNGs accumulate with no retention; `tkinter` is not thread-safe, and the worker touches it only through `after`.

## Take care of later

1. Keep the working-tree `load_config` and `test_config.py`. Do not restore the `HEAD` version of `load_config`. When you next commit, those two changes belong together. Add pytest somewhere the venv can install it; it is not there now.
2. Make Start stay disabled until the worker has left `_capture_loop`, and stop using the `"Idle"` substring as the signal between `_stop` and `_on_worker_stopped`.
3. On close, either wait out the current grab or stop calling `after` after `destroy`. Two seconds is shorter than a stalled `mss` grab.
4. Decide what `_on_close` should do with a file `load_config` refused to rewrite. Preserve unknown keys if you still want hand-edited JSON to survive a window close, and catch `OSError` from `save_config`.
5. Teach Analyze which interval to use, or store it, if sessions must stay stable when the form changes. Duration currently excludes the interval after the last shot; change that only if that is the number you want.
6. Add tests for `group_sessions` (gap equal to `1.5 * interval`, collision suffix, non-matching names) and `unique_path` (existing file, 1000th collision). The GUI was not tested.
7. Update `README.md` so Stop is not described as pause, and so Analyze is mentioned.

## Ideas to improve

- Write each PNG to a temporary name and replace, so a crash mid-save is less likely to leave a partial file with a real timestamp name.
- Keep one `mss` instance for the life of the worker thread instead of opening it on every shot. Create it on that thread.
- Speculative: per-monitor or region capture. The current `monitors[0]` grab is the whole virtual desktop on purpose.
- Speculative: a retention cap (count or age) so `captures/` cannot fill the disk.
- Speculative: tray icon or “start with Windows”. There is no shell integration now.
- Speculative: a real Pause that keeps `_session_count` and the remaining wait. That would match the README wording; the code does not do it today.

## Conventions for future edits

Python 3.10, type hints, `from __future__ import annotations`, `tkinter.ttk`, one module. Match the existing style. New behavior fits in `main.py` until a split is deliberate; a later LLM should not invent a package layout for a one-file app.

Read first: this file, `main.py`, `test_config.py`, `README.md`, `requirements.txt`.

Do not “clean up” these; they are intentional:

- `sct.monitors[0]` is the full virtual desktop, including every monitor.
- The capture loop’s bare `except Exception` is marked `noqa: BLE001` so the UI keeps looping.
- Status updates use `lambda m=msg:` so the worker does not close over a changing loop variable.
- `test_config.py` must insert the `mss` / `PIL` mocks before `import main`.
- `load_config` must not write the file when JSON is corrupt or `interval_seconds` is not an int. The tests assert the bytes on disk stay put.
- `_001`-style suffixes are same-second collisions. Do not parse them as milliseconds.
- `config.json`, `captures/`, and `*.png` are gitignored so local screenshots and paths stay out of git.
- `GAP_FACTOR` is the only knob for session gaps. Analysis does not read file mtimes.
