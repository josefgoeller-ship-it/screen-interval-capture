"""load_config must tolerate invalid interval_seconds without rewriting the file.

mss and PIL are mocked on sys.modules before main is imported. These tests
do not open a window or grab the screen.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

sys.modules.setdefault("mss", MagicMock())
_pil = ModuleType("PIL")
_pil.Image = MagicMock()
sys.modules.setdefault("PIL", _pil)
sys.modules.setdefault("PIL.Image", _pil.Image)

import pytest

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import main  # noqa: E402


@pytest.fixture
def config_file(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    monkeypatch.setattr(main, "CONFIG_PATH", path)
    return path


def test_invalid_interval_string_returns_defaults_without_overwrite(config_file):
    original = {"output_folder": "C:/captures", "interval_seconds": "not-a-number"}
    config_file.write_text(json.dumps(original), encoding="utf-8")
    loaded = main.load_config()
    assert loaded["interval_seconds"] == main.DEFAULT_INTERVAL
    assert loaded["output_folder"] == "C:/captures"
    on_disk = json.loads(config_file.read_text(encoding="utf-8"))
    assert on_disk == original


def test_invalid_interval_type_returns_defaults_without_overwrite(config_file):
    original = {"output_folder": "C:/captures", "interval_seconds": {"bad": True}}
    config_file.write_text(json.dumps(original), encoding="utf-8")
    loaded = main.load_config()
    assert loaded["interval_seconds"] == main.DEFAULT_INTERVAL
    on_disk = json.loads(config_file.read_text(encoding="utf-8"))
    assert on_disk == original


def test_missing_config_writes_defaults(config_file):
    assert not config_file.exists()
    loaded = main.load_config()
    assert loaded == {
        "output_folder": str(main.DEFAULT_OUTPUT),
        "interval_seconds": main.DEFAULT_INTERVAL,
    }
    assert json.loads(config_file.read_text(encoding="utf-8")) == loaded


def test_bad_json_and_non_object_return_defaults_without_overwrite(config_file):
    config_file.write_text("{", encoding="utf-8")
    loaded = main.load_config()
    assert loaded["interval_seconds"] == main.DEFAULT_INTERVAL
    assert config_file.read_text(encoding="utf-8") == "{"

    config_file.write_text("null", encoding="utf-8")
    loaded = main.load_config()
    assert loaded["output_folder"] == str(main.DEFAULT_OUTPUT)
    assert config_file.read_text(encoding="utf-8") == "null"


def test_non_positive_interval_and_blank_folder_are_preserved(config_file):
    original = {"output_folder": "", "interval_seconds": 0}
    config_file.write_text(json.dumps(original), encoding="utf-8")
    loaded = main.load_config()
    assert loaded["interval_seconds"] == 0
    assert loaded["output_folder"] == str(main.DEFAULT_OUTPUT)

    config_file.write_text(
        json.dumps({"output_folder": "C:/captures", "interval_seconds": -5}),
        encoding="utf-8",
    )
    loaded = main.load_config()
    assert loaded["interval_seconds"] == -5
    assert loaded["output_folder"] == "C:/captures"
    assert json.loads(config_file.read_text(encoding="utf-8"))["interval_seconds"] == -5


def test_parse_capture_time_suffix_and_invalid_calendar_date():
    assert main.parse_capture_time(Path("2024-01-02_03-04-05_007.PNG")) == datetime(
        2024, 1, 2, 3, 4, 5
    )
    assert main.parse_capture_time(Path("2024-13-40_99-99-99.png")) is None
    assert main.parse_capture_time(Path("shot.png")) is None


def test_group_sessions_keeps_gap_at_factor_and_splits_above_it():
    interval = 60
    first = Path("2024-06-01_12-00-00.png")
    at_limit = Path("2024-06-01_12-01-30.png")
    beyond = Path("2024-06-01_12-03-01.png")
    sessions = main.group_sessions(
        [beyond, Path("notes.png"), first, at_limit],
        interval,
    )
    assert len(sessions) == 2
    assert [path.name for path in sessions[0].files] == [first.name, at_limit.name]
    assert sessions[0].duration_seconds == 90
    assert [path.name for path in sessions[1].files] == [beyond.name]
    assert main.group_sessions([Path("notes.png")], interval) == []


def test_unique_path_suffix_then_raises_when_exhausted(tmp_path):
    stamp = "2024-01-01_00-00-00"
    (tmp_path / f"{stamp}.png").write_bytes(b"")
    collided = main.unique_path(tmp_path, stamp)
    assert collided.name == f"{stamp}_001.png"

    for n in range(1, 1000):
        (tmp_path / f"{stamp}_{n:03d}.png").write_bytes(b"")
    with pytest.raises(OSError, match=stamp):
        main.unique_path(tmp_path, stamp)
