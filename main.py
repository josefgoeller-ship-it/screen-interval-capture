"""Windows GUI that saves full-desktop PNGs on a timer and groups them into sessions.

Entry is `python main.py` (`ScreenIntervalApp`). Capture uses mss
monitors[0] (the virtual desktop) and Pillow, on a daemon worker thread.
Filenames are local YYYY-MM-DD_HH-MM-SS.png. `unique_path` adds _001–_999
on collisions, then raises OSError; those suffixes are not milliseconds.
`load_config` writes defaults only when config.json is missing. Bad JSON
or a non-numeric interval returns defaults in memory and does not rewrite
the file. Interval 0 or a negative int is returned as-is. `save_config`
replaces the file with two keys and is not atomic. Analyze splits sessions
when filename gaps exceed 1.5 times the interval currently in the form.
Status updates from the worker go through `after`. Stop does not wait for
the in-flight grab.
"""

from __future__ import annotations

import json
import re
import threading
import time
import tkinter as tk
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import mss
from PIL import Image

APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "config.json"
DEFAULT_OUTPUT = APP_DIR / "captures"
DEFAULT_INTERVAL = 60
GAP_FACTOR = 1.5
TIMESTAMP_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})(?:_\d{3})?\.png$",
    re.IGNORECASE,
)


def load_config() -> dict:
    defaults = {
        "output_folder": str(DEFAULT_OUTPUT),
        "interval_seconds": DEFAULT_INTERVAL,
    }
    if not CONFIG_PATH.exists():
        save_config(defaults)
        return defaults
    try:
        with CONFIG_PATH.open(encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return defaults
    if not isinstance(data, dict):
        return defaults
    try:
        interval = int(data.get("interval_seconds", defaults["interval_seconds"]))
    except (ValueError, TypeError):
        interval = defaults["interval_seconds"]
    return {
        "output_folder": str(data.get("output_folder") or defaults["output_folder"]),
        "interval_seconds": interval,
    }


def save_config(config: dict) -> None:
    with CONFIG_PATH.open("w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)


def unique_path(folder: Path, stamp: str) -> Path:
    base = folder / f"{stamp}.png"
    if not base.exists():
        return base
    for n in range(1, 1000):
        candidate = folder / f"{stamp}_{n:03d}.png"
        if not candidate.exists():
            return candidate
    raise OSError(f"Too many files for timestamp {stamp}")


def capture_screen(folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    path = unique_path(folder, stamp)
    with mss.MSS() as sct:
        # monitors[0] is the virtual desktop spanning all displays
        shot = sct.grab(sct.monitors[0])
        image = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        image.save(path, format="PNG")
    return path


@dataclass
class Session:
    start: datetime
    end: datetime
    files: list[Path]

    @property
    def duration_seconds(self) -> float:
        return (self.end - self.start).total_seconds()


def parse_capture_time(path: Path) -> datetime | None:
    match = TIMESTAMP_RE.match(path.name)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y-%m-%d_%H-%M-%S")
    except ValueError:
        return None


def format_duration(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}"


def group_sessions(paths: list[Path], interval_seconds: int) -> list[Session]:
    timed: list[tuple[datetime, Path]] = []
    for path in paths:
        stamp = parse_capture_time(path)
        if stamp is not None:
            timed.append((stamp, path))
    timed.sort(key=lambda item: (item[0], item[1].name))

    if not timed:
        return []

    max_gap = interval_seconds * GAP_FACTOR
    sessions: list[Session] = []
    current_files = [timed[0][1]]
    current_start = timed[0][0]
    current_end = timed[0][0]

    for prev, curr in zip(timed, timed[1:]):
        gap = (curr[0] - prev[0]).total_seconds()
        if gap <= max_gap:
            current_files.append(curr[1])
            current_end = curr[0]
        else:
            sessions.append(Session(start=current_start, end=current_end, files=current_files))
            current_files = [curr[1]]
            current_start = curr[0]
            current_end = curr[0]

    sessions.append(Session(start=current_start, end=current_end, files=current_files))
    return sessions


class ScreenIntervalApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Screen Interval Capture")
        self.resizable(True, True)
        self.minsize(480, 220)

        self._stop_event = threading.Event()
        self._worker: threading.Thread | None = None
        self._session_count = 0

        config = load_config()
        self.folder_var = tk.StringVar(value=config["output_folder"])
        self.interval_var = tk.StringVar(value=str(config["interval_seconds"]))
        self.status_var = tk.StringVar(value="Idle")

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        pad = {"padx": 10, "pady": 6}
        frame = ttk.Frame(self, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")

        ttk.Label(frame, text="Output folder").grid(row=0, column=0, sticky="w", **pad)
        folder_row = ttk.Frame(frame)
        folder_row.grid(row=1, column=0, columnspan=2, sticky="ew", **pad)
        self.folder_entry = ttk.Entry(folder_row, textvariable=self.folder_var, width=48)
        self.folder_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.browse_btn = ttk.Button(folder_row, text="Browse…", command=self._browse)
        self.browse_btn.pack(side=tk.LEFT, padx=(8, 0))

        ttk.Label(frame, text="Interval (seconds)").grid(row=2, column=0, sticky="w", **pad)
        self.interval_spin = ttk.Spinbox(
            frame,
            from_=1,
            to=86400,
            textvariable=self.interval_var,
            width=10,
        )
        self.interval_spin.grid(row=2, column=1, sticky="w", **pad)

        btn_row = ttk.Frame(frame)
        btn_row.grid(row=3, column=0, columnspan=2, sticky="ew", **pad)
        self.start_btn = ttk.Button(btn_row, text="Start", command=self._start)
        self.start_btn.pack(side=tk.LEFT)
        self.stop_btn = ttk.Button(btn_row, text="Stop", command=self._stop, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=(8, 0))
        self.analyze_btn = ttk.Button(btn_row, text="Analyze", command=self._analyze)
        self.analyze_btn.pack(side=tk.LEFT, padx=(8, 0))

        ttk.Label(frame, textvariable=self.status_var, wraplength=440).grid(
            row=4, column=0, columnspan=2, sticky="w", **pad
        )

    def _browse(self) -> None:
        chosen = filedialog.askdirectory(initialdir=self.folder_var.get() or str(DEFAULT_OUTPUT))
        if chosen:
            self.folder_var.set(chosen)

    def _analyze(self) -> None:
        interval = self._parse_interval()
        if interval is None:
            return
        folder = Path(self.folder_var.get().strip() or str(DEFAULT_OUTPUT))
        if not folder.is_dir():
            messagebox.showinfo("Analyze", f"Folder not found:\n{folder}")
            return
        try:
            pngs = sorted(folder.glob("*.png"))
        except OSError as exc:
            messagebox.showerror("Analyze", f"Cannot read folder:\n{exc}")
            return

        sessions = group_sessions(pngs, interval)
        if not sessions:
            messagebox.showinfo(
                "Analyze",
                "No timestamped PNG screenshots found in this folder.",
            )
            return
        SessionAnalysisWindow(self, folder, interval, sessions)

    def _parse_interval(self) -> int | None:
        try:
            value = int(self.interval_var.get().strip())
        except ValueError:
            messagebox.showerror("Invalid interval", "Interval must be a whole number of seconds.")
            return None
        if value < 1:
            messagebox.showerror("Invalid interval", "Interval must be at least 1 second.")
            return None
        return value

    def _set_running_ui(self, running: bool) -> None:
        state = tk.DISABLED if running else tk.NORMAL
        self.folder_entry.configure(state=state)
        self.browse_btn.configure(state=state)
        self.interval_spin.configure(state=state)
        self.start_btn.configure(state=tk.DISABLED if running else tk.NORMAL)
        self.stop_btn.configure(state=tk.NORMAL if running else tk.DISABLED)

    def _start(self) -> None:
        if self._worker and self._worker.is_alive():
            return
        interval = self._parse_interval()
        if interval is None:
            return
        folder = Path(self.folder_var.get().strip() or str(DEFAULT_OUTPUT))
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            messagebox.showerror("Folder error", f"Cannot create or access folder:\n{exc}")
            return

        save_config({"output_folder": str(folder), "interval_seconds": interval})
        self.folder_var.set(str(folder))
        self.interval_var.set(str(interval))

        self._session_count = 0
        self._stop_event.clear()
        self._set_running_ui(True)
        self.status_var.set(f"Running — next capture immediately (every {interval}s)")
        self._worker = threading.Thread(
            target=self._capture_loop,
            args=(folder, interval),
            daemon=True,
        )
        self._worker.start()

    def _stop(self) -> None:
        self._stop_event.set()
        self._set_running_ui(False)
        self.status_var.set(
            f"Idle — stopped. Session captures: {self._session_count}"
        )

    def _capture_loop(self, folder: Path, interval: int) -> None:
        while not self._stop_event.is_set():
            started = time.monotonic()
            try:
                path = capture_screen(folder)
                self._session_count += 1
                msg = (
                    f"Running — last: {path.name} | "
                    f"session: {self._session_count} | "
                    f"next in {interval}s"
                )
            except Exception as exc:  # noqa: BLE001 — surface to UI, keep looping
                msg = f"Error: {exc} — retrying in {interval}s"
            self.after(0, lambda m=msg: self.status_var.set(m))

            remaining = interval - (time.monotonic() - started)
            if remaining > 0:
                self._stop_event.wait(remaining)

        self.after(0, self._on_worker_stopped)

    def _on_worker_stopped(self) -> None:
        self._set_running_ui(False)
        if "Idle" not in self.status_var.get():
            self.status_var.set(
                f"Idle — stopped. Session captures: {self._session_count}"
            )

    def _on_close(self) -> None:
        self._stop_event.set()
        if self._worker and self._worker.is_alive():
            self._worker.join(timeout=2.0)
        interval = self._parse_interval()
        if interval is not None:
            save_config(
                {
                    "output_folder": self.folder_var.get().strip() or str(DEFAULT_OUTPUT),
                    "interval_seconds": interval,
                }
            )
        self.destroy()


class SessionAnalysisWindow(tk.Toplevel):
    def __init__(
        self,
        master: tk.Tk,
        folder: Path,
        interval_seconds: int,
        sessions: list[Session],
    ) -> None:
        super().__init__(master)
        self.title("Session analysis")
        self.geometry("720x420")
        self.minsize(560, 320)
        self.transient(master)
        self._sessions = sessions

        pad = {"padx": 8, "pady": 4}
        frame = ttk.Frame(self, padding=10)
        frame.grid(row=0, column=0, sticky="nsew")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)
        frame.rowconfigure(3, weight=1)

        ttk.Label(
            frame,
            text=(
                f"{folder} — {len(sessions)} session(s), "
                f"gap ≤ {GAP_FACTOR:g}×{interval_seconds}s"
            ),
        ).grid(row=0, column=0, sticky="w", **pad)

        list_frame = ttk.Frame(frame)
        list_frame.grid(row=1, column=0, sticky="nsew", **pad)
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)

        columns = ("num", "start", "end", "duration", "shots")
        self.tree = ttk.Treeview(
            list_frame,
            columns=columns,
            show="headings",
            selectmode="browse",
            height=8,
        )
        self.tree.heading("num", text="#")
        self.tree.heading("start", text="Start")
        self.tree.heading("end", text="End")
        self.tree.heading("duration", text="Duration")
        self.tree.heading("shots", text="Shots")
        self.tree.column("num", width=40, anchor="center")
        self.tree.column("start", width=150)
        self.tree.column("end", width=150)
        self.tree.column("duration", width=90, anchor="center")
        self.tree.column("shots", width=60, anchor="center")

        scroll = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")

        for index, session in enumerate(sessions, start=1):
            self.tree.insert(
                "",
                tk.END,
                iid=str(index - 1),
                values=(
                    index,
                    session.start.strftime("%Y-%m-%d %H:%M:%S"),
                    session.end.strftime("%Y-%m-%d %H:%M:%S"),
                    format_duration(session.duration_seconds),
                    len(session.files),
                ),
            )

        ttk.Label(frame, text="Screenshots in selected session").grid(
            row=2, column=0, sticky="w", **pad
        )
        detail_frame = ttk.Frame(frame)
        detail_frame.grid(row=3, column=0, sticky="nsew", **pad)
        detail_frame.columnconfigure(0, weight=1)
        detail_frame.rowconfigure(0, weight=1)

        self.detail = tk.Listbox(detail_frame, height=8)
        detail_scroll = ttk.Scrollbar(
            detail_frame, orient=tk.VERTICAL, command=self.detail.yview
        )
        self.detail.configure(yscrollcommand=detail_scroll.set)
        self.detail.grid(row=0, column=0, sticky="nsew")
        detail_scroll.grid(row=0, column=1, sticky="ns")

        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        if sessions:
            self.tree.selection_set("0")
            self.tree.focus("0")
            self._show_session(0)

    def _on_select(self, _event: object = None) -> None:
        selected = self.tree.selection()
        if not selected:
            return
        self._show_session(int(selected[0]))

    def _show_session(self, index: int) -> None:
        self.detail.delete(0, tk.END)
        for path in self._sessions[index].files:
            self.detail.insert(tk.END, path.name)


def main() -> None:
    app = ScreenIntervalApp()
    app.mainloop()


if __name__ == "__main__":
    main()
