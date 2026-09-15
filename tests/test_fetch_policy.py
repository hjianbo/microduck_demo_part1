from pathlib import Path
import importlib.util

import pytest


_SPEC = importlib.util.spec_from_file_location("fetch_policy", Path("scripts/fetch_policy.py"))
assert _SPEC is not None and _SPEC.loader is not None
fetch_policy = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(fetch_policy)


POINTER = (
    b"version https://git-lfs.github.com/spec/v1\n"
    b"oid sha256:e36332d383997d51401897734cd3e79cf5038406feddb18b4d57ecfb141daa6c\n"
    b"size 793705\n"
)


def test_digest_reads_plain_lfs_pointer(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pointer = tmp_path / "policy.onnx"
    pointer.write_bytes(POINTER)
    monkeypatch.setattr(fetch_policy, "POINTER", pointer)
    assert fetch_policy.expected_digest() == "e36332d383997d51401897734cd3e79cf5038406feddb18b4d57ecfb141daa6c"


def test_digest_uses_committed_pointer_for_hydrated_model(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    model = tmp_path / "policy.onnx"
    model.write_bytes(b"\x08\x8fhydrated-onnx-binary")
    monkeypatch.setattr(fetch_policy, "POINTER", model)
    monkeypatch.setattr(fetch_policy.subprocess, "check_output", lambda *args, **kwargs: POINTER)
    assert fetch_policy.expected_digest() == "e36332d383997d51401897734cd3e79cf5038406feddb18b4d57ecfb141daa6c"


def test_invalid_committed_pointer_has_clear_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    model = tmp_path / "policy.onnx"
    model.write_bytes(b"\x08\x8fhydrated-onnx-binary")
    monkeypatch.setattr(fetch_policy, "POINTER", model)
    monkeypatch.setattr(fetch_policy.subprocess, "check_output", lambda *args, **kwargs: b"not-lfs")
    with pytest.raises(RuntimeError, match="Expected a Git LFS pointer"):
        fetch_policy.expected_digest()
