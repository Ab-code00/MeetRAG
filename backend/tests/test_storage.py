from pathlib import Path

import app.services.storage as storage
from app.services.storage import LOCAL_STORAGE_ROOT, get_local_path, safe_filename


def test_safe_filename_caps_length() -> None:
    filename = "v" * 200 + ".mp4"
    result = safe_filename(filename)
    # The cap clips the extension mid-name; harmless because the temp suffix
    # derives from original_filename, not the stored path.
    assert result == "v" * 100


def test_safe_filename_strips_dangerous_characters() -> None:
    assert safe_filename("my<file>:name?.mp4") == "my-file-name-.mp4"


def test_get_local_path_flattens_object_key() -> None:
    key = "tenants/t1/meetings/m1/recording-abc/some-file.mp4"
    path = get_local_path(key)
    assert path == LOCAL_STORAGE_ROOT / "recording-abc" / "some-file.mp4"


def test_get_local_path_stays_under_windows_max_path() -> None:
    key = (
        "tenants/"
        + "t" * 36
        + "/meetings/"
        + "m" * 36
        + "/"
        + "r" * 36
        + "/"
        + safe_filename("v" * 200 + ".mp4")
    )
    path = get_local_path(key)
    assert len(str(path)) < 260
    assert isinstance(path, Path)


def test_resolve_local_path_prefers_flattened(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "local_storage" / "recordings"
    monkeypatch.setattr(storage, "LOCAL_STORAGE_ROOT", root)
    key = "tenants/t1/meetings/m1/rec-abc/some.mp4"

    flat = storage.get_local_path(key)
    flat.parent.mkdir(parents=True, exist_ok=True)
    flat.write_bytes(b"new")

    legacy = storage._legacy_local_path(key)
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_bytes(b"old")

    resolved = storage._resolve_local_path(key)
    assert resolved == flat
    assert resolved.read_bytes() == b"new"


def test_resolve_local_path_falls_back_to_legacy(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "local_storage" / "recordings"
    monkeypatch.setattr(storage, "LOCAL_STORAGE_ROOT", root)
    key = "tenants/t1/meetings/m1/rec-legacy/old-file.mp4"

    legacy = storage._legacy_local_path(key)
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_bytes(b"x")

    resolved = storage._resolve_local_path(key)
    assert resolved == legacy
    assert resolved.read_bytes() == b"x"


def test_save_then_download_round_trip(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "local_storage" / "recordings"
    monkeypatch.setattr(storage, "LOCAL_STORAGE_ROOT", root)
    # Force the local-filesystem branch regardless of S3 env config.
    monkeypatch.setattr(storage, "_storage_available", lambda: False)
    key = "tenants/t1/meetings/m1/rec-roundtrip/interview-long-name.mp4"
    content = b"audio-bytes"

    storage.save_file_locally(key, content)
    destination = str(tmp_path / "copy.mp4")
    storage.download_recording(key, destination)

    assert Path(destination).read_bytes() == content
