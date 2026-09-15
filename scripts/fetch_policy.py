#!/usr/bin/env python3
"""Download and verify the LFS-backed walking policy at the pinned Space revision."""

from hashlib import sha256
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SPACE = ROOT / "vendor/microduck_simulator"
FILENAME = "app/public/policies/BEST_alpha_walking.onnx"
POINTER = SPACE / FILENAME
TARGET = ROOT / ".demo/models/BEST_alpha_walking.onnx"


def _digest_from_lfs_pointer(contents: bytes, source: str) -> str:
    try:
        lines = contents.decode("ascii").splitlines()
    except UnicodeDecodeError as exc:
        raise RuntimeError(f"Expected a Git LFS pointer at {source}") from exc
    for line in lines:
        if line.startswith("oid sha256:"):
            return line.removeprefix("oid sha256:")
    raise RuntimeError(f"Expected a Git LFS pointer at {source}")


def expected_digest() -> str:
    working_tree_contents = POINTER.read_bytes()
    if working_tree_contents.startswith(b"version https://git-lfs.github.com/spec/"):
        return _digest_from_lfs_pointer(working_tree_contents, str(POINTER))

    # Git LFS may automatically hydrate the working tree file. Read the blob
    # recorded by the pinned submodule commit to retain independent checksum
    # verification instead of trusting the hydrated binary as its own source.
    committed_pointer = subprocess.check_output(
        ["git", "-C", str(SPACE), "show", f"HEAD:{FILENAME}"]
    )
    return _digest_from_lfs_pointer(committed_pointer, f"{SPACE}@HEAD:{FILENAME}")


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
    from huggingface_hub import hf_hub_download

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
