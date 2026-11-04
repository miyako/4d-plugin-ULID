#!/usr/bin/env python3
"""Download an explicitly selected, checksum-pinned tool4d runtime for manual CI."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import tarfile
from urllib.parse import urlparse
import urllib.request


def extract(archive, destination, expected_sha, runtime_path):
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha):
        raise ValueError("Expected SHA-256 must be 64 lowercase hexadecimal characters")
    with archive.open("rb") as source:
        actual = hashlib.file_digest(source, "sha256").hexdigest()
    if actual != expected_sha:
        raise ValueError("Runtime archive checksum mismatch")
    path = PurePosixPath(runtime_path)
    if (path.is_absolute() or ".." in path.parts or "\\" in runtime_path
            or ":" in runtime_path or not path.parts
            or any(ord(character) < 32 for character in runtime_path)):
        raise ValueError("Runtime path must be a portable relative path")
    if destination.exists():
        raise ValueError("Runtime destination must not already exist")
    destination.mkdir(parents=True)
    with tarfile.open(archive, "r:xz") as tar:
        # Python's data filter rejects traversal, external links and special files.
        tar.extractall(destination, filter="data")
    runtime = destination.joinpath(*path.parts)
    if not runtime.is_file() or not runtime.resolve().is_relative_to(destination.resolve()):
        raise ValueError("Runtime executable is missing or outside its archive")
    if os.name != "nt" and not os.access(runtime, os.X_OK):
        raise ValueError("Runtime executable lacks executable permissions")
    return runtime.resolve()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--runtime-path", required=True)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    if urlparse(args.url).scheme != "https":
        raise ValueError("Runtime download requires HTTPS")
    if not re.fullmatch(r"[0-9a-f]{64}", args.sha256):
        raise ValueError("Provide the independently verified archive SHA-256 before downloading")
    args.archive.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(args.url, timeout=120) as response:
        if urlparse(response.url).scheme != "https":
            raise ValueError("Runtime download redirected outside HTTPS")
        with args.archive.open("xb") as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
    runtime = extract(args.archive, args.destination, args.sha256, args.runtime_path)
    args.report.write_text(json.dumps({
        "url": args.url, "sha256": args.sha256, "runtime_path": args.runtime_path,
    }, indent=2) + "\n")
    with open(os.environ["GITHUB_OUTPUT"], "a") as output:
        output.write(f"runtime={runtime.as_posix()}\n")


if __name__ == "__main__":
    main()
