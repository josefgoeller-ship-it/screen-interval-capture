# LLM handoff: screen-interval-capture

An earlier `HANDOFF.md` is in this repo. This file is the coding-agent handoff. If they disagree, trust the code.

## What this project is

A Windows desktop GUI that grabs the full virtual desktop on a timer and saves PNG files named by local capture time. Analyze groups those filenames into sessions. The audience is the person running it on their own machine as a screen time-lapse. It is one module, not a library. README describes Start and Stop. The window also has Analyze, which the README does not mention.

## How to run and test

From `C:\MyProjects\screen-interval-capture`. No environment variables. No `pyproject.toml`. `requirements.txt`: `mss>=9.0.1`, `Pillow>=10.0.0`. `tkinter` is the standard library. pytest is not listed in `requirements.txt`.

```text
python -m pip install -r requirements.txt
python main.py
python -m pytest -q test_config.py
```

This session ran `python -m pytest -q test_config.py`: 2 passed. The GUI was not opened and no screenshot was taken. `mss` and `PIL` are mocked in the test before `main` is imported, so the tests do not need a display.

`config.json` next to `main.py` stores `output_folder` and `interval_seconds`. It is created when missing. The copy on disk at documentation time pointed at `captures` under this repo with interval 60. `captures/` is output images, not source.

## Repository map

- `main.py` — config, capture, session grouping, both windows.
- `test_config.py` — `load_config` only.
- `config.json` — local settings (gitignored).
- `requirements.txt`, `README.md`, `HANDOFF.md`.

## Runtime flow

`main()` builds `ScreenIntervalApp` and runs `mainloop()`. Startup calls `load_config`.

Start: `_parse_interval` requires a whole number of seconds, at least 1 (no upper bound in this check; the spinbox is 1–86400, but a typed value above that still passes). The folder is created. `save_config` writes the two keys. The form locks. A daemon thread runs `_capture_loop`.

Each pass calls `capture_screen`: `mss.MSS().grab(monitors[0])` (every display as one virtual desktop), then `Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")`, saved as PNG. The name is local `YYYY-MM-DD_HH-MM-SS.png`. Status text is applied with `after(0, ...)`. Any exception is shown and the loop continues. The thread waits the rest of the interval with `Event.wait`. If the grab took longer than the interval, it does not wait.

Stop sets the event, unlocks the form immediately, and sets an Idle status. When the worker leaves the loop it schedules `_on_worker_stopped`, which sets Idle only if the current status text does not already contain `"Idle"`.

Close sets the event, joins the worker for up to 2 seconds, saves config if the interval field parses, then `destroy()`.

Analyze lists `*.png` in the folder (not subfolders) and opens `SessionAnalysisWindow` on `group_sessions`. A session's duration is the last filename time minus the first. One file is `0:00:00`. Images are not decoded.

## Invariants and footguns

- `sct.monitors[0]` is the full virtual desktop on purpose.
- `unique_path` writes `stamp_001.png` through `stamp_999.png`, then raises `OSError`. Those suffixes are a collision counter, not milliseconds. `parse_capture_time` keeps only the `YYYY-MM-DD_HH-MM-SS` group, so suffixed files share a timestamp with the unsuffixed file. The regex is case-insensitive. The listing pattern is `*.png`.
- `load_config` writes defaults only when `config.json` is missing. `JSONDecodeError` or `OSError` returns defaults and does not rewrite the file. A non-numeric `interval_seconds` (string or non-int) falls back to 60 in memory and does not rewrite the file. Integer `0` and negative integers are returned as-is. Floats are truncated with `int()`.
- `save_config` replaces the whole file with exactly two keys. It is not atomic and has no `try`. Start and window close call it. Opening the app (bad interval replaced in memory by 60) and closing it overwrites the file, so the invalid value and any extra keys are lost. A corrupt JSON file is likewise replaced on close, because the form is then showing defaults and the interval parses.
- Sessions split when the gap between filename times is greater than `interval_seconds * GAP_FACTOR` (`GAP_FACTOR` is 1.5). Files do not store the interval they were taken with. Analyze uses the interval currently in the form.
- `_session_count` is in memory for the current Start/Stop run. It resets to 0 on every Start. Analysis ignores it.
- Stop does not wait for the in-flight grab. `_start` returns immediately when the worker is still alive, with no message. The worker can then queue a status string that begins with `Running —` after Stop.
- The worker is a daemon. Close joins for 2 seconds, which can be shorter than a stalled grab. A later `after(...)` can run against a window that is already being destroyed.
- Status updates use `lambda m=msg:` so the worker does not close over a changing loop variable.
- The capture loop's `except Exception` is marked so the UI keeps looping.
- Two processes capturing the same folder can race in `unique_path` (check then create, no lock). Not reproduced here.

## Still broken or unfinished

- README says Stop pauses. Stop ends the loop. The next Start resets `_session_count` and captures immediately. README does not mention Analyze.
- The "do not rewrite bad config" rule stops at `load_config`. Close and Start still call `save_config`.
- `load_config` does not enforce the UI minimum. Start and Analyze reject values below 1. A stored `0` survives load and fails only when the user starts or analyzes.
- pytest is not in `requirements.txt`. The two tests passed on the `python` that already had pytest. There are no tests for `unique_path`, `capture_screen`, `group_sessions`, or the GUI.
- The main window grids its frame `sticky="nsew"` but never sets root row/column weights. Status `wraplength` is fixed at 440. The analysis window does set weights.
- Whether `*.PNG` is included by `glob("*.png")` was not tested on this machine.
- This session did not launch the GUI, so the Stop/status race and the close-during-grab path were read, not reproduced.

## Good next improvements

1. Keep Start disabled until the worker has left `_capture_loop`, and stop using the `"Idle"` substring as the signal between `_stop` and `_on_worker_stopped`.
2. On close, wait out the current grab or stop calling `after` after `destroy`.
3. Decide what close should do with a file `load_config` refused to rewrite. Preserve unknown keys if hand-edited JSON should survive, and catch `OSError` from `save_config`.
4. Add tests for `group_sessions` (gap equal to `1.5 * interval`, collision suffix, non-matching names) and `unique_path` (existing file, 1000th collision).
5. Update the README so Stop is not described as pause, and so Analyze is mentioned.

## Files a later agent will touch most

`main.py` (`load_config`, `save_config`, `_capture_loop`, `_stop`, `_on_close`, `group_sessions`) and `test_config.py`.

## What not to change without a product decision

- Do not change `monitors[0]` to a single display unless capture is supposed to drop the other screens.
- Do not remove the bare `except Exception` around the grab. The loop is supposed to keep running.
- Do not make `load_config` rewrite the file when JSON is corrupt or the interval is not a number. The tests lock the current behavior.
- Do not treat `_NNN` as milliseconds.
- Do not start a package layout for this one-file app unless a split is the task.

## Recent behavior you must not regress

- Invalid `interval_seconds` (non-numeric string or non-int) returns the default 60 and leaves the file bytes unchanged.
- JSON that does not parse returns defaults and does not call `save_config`.
- A missing config file is the case that writes defaults.
- `test_config.py` inserts `mss` and `PIL` mocks before `import main`.
- Capture status from the worker goes through `after`, with the loop variable bound in the lambda default.
