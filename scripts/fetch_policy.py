#!/usr/bin/env python3
"""Download and verify the LFS-backed walking policy at the pinned Space revision."""

from hashlib import sha256
from pathlib import Path
import shutil
import subprocess

from huggingface_hub import hf_hub_download


ROOT = Path(__file__).resolve().parents[1]
SPACE = ROOT / "vendor/microduck_simulator"
FILENAME = "app/public/policies/BEST_alpha_walking.onnx"
POINTER = SPACE / FILENAME
TARGET = ROOT / ".demo/models/BEST_alpha_walking.onnx"


def expected_digest() -> str:
    for line in POINTER.read_text(encoding="utf-8").splitlines():
        if line.startswith("oid sha256:"):
            return line.removeprefix("oid sha256:")
    raise RuntimeError(f"Expected a Git LFS pointer at {POINTER}")


def digest(path: Path) -> str:
    hasher = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def main() -> None:
    wanted = expected_digest()
    if TARGET.is_file() and digest(TARGET) == wanted:
        print(f"Verified cached walking policy: {TARGET.relative_to(ROOT)}")
        return

    revision = subprocess.check_output(
        ["git", "-C", str(SPACE), "rev-parse", "HEAD"], text=True
    ).strip()
    downloaded = Path(
        hf_hub_download(
            repo_id="pollen-robotics/microduck-simulator",
            repo_type="space",
            filename=FILENAME,
            revision=revision,
        )
    )
    if digest(downloaded) != wanted:
        raise RuntimeError("Downloaded walking policy does not match the pinned LFS digest")
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(downloaded, TARGET)
    print(f"Downloaded and verified walking policy: {TARGET.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
