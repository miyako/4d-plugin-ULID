#!/usr/bin/env python3
"""Publish only after a new draft's assets match the final signed distribution."""
import hashlib
import os
from pathlib import Path
import re
import subprocess

from artifacts import revision
from preflight import PUBLICATIONS


def asset_bytes(directory):
    assets = {}
    for path in directory.iterdir():
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"Expected regular release asset: {path}")
        assets[path.name] = path.read_bytes()
    return assets


def verify_checksums(assets):
    entries = {}
    for line in assets["SHA256SUMS"].decode("utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64}) [ *](?:\./)?([^/\\]+)", line)
        if not match or match[2] in entries:
            raise ValueError("Invalid or duplicate SHA256SUMS entry")
        entries[match[2]] = match[1]
    actual = {name: hashlib.sha256(data).hexdigest()
              for name, data in assets.items() if name != "SHA256SUMS"}
    if not actual or entries != actual:
        raise ValueError("Release asset checksums differ or are incomplete")


def verify_download(expected, directory):
    downloaded = asset_bytes(directory)
    if downloaded != expected:
        raise ValueError("Draft assets differ from final signed asset bytes")
    verify_checksums(downloaded)


def release(tag, sha, publication, dist, downloaded):
    if publication not in PUBLICATIONS:
        raise ValueError("Explicit create-draft or publish authorization required")
    if not re.fullmatch(r"v(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)", tag):
        raise ValueError("Tag must be vX.Y.Z")
    revision(sha)
    expected = asset_bytes(dist)
    verify_checksums(expected)
    downloaded.mkdir()

    def gh(*args):
        subprocess.run(["gh", "release", *args], check=True)

    gh("create", tag, "--draft", "--prerelease=false", "--latest=false",
       "--target", sha, "--title", tag, "--notes",
       "Developer ID signed and notarized macOS universal plugin; Windows x64 plugin is UNSIGNED. "
       f"See RELEASE.md and attached provenance/checksums. Built from {sha}.")
    gh("upload", tag, *(str(dist / name) for name in sorted(expected)))
    gh("download", tag, "--dir", str(downloaded))
    verify_download(expected, downloaded)
    if publication == "publish":
        gh("edit", tag, "--draft=false", "--prerelease=false", "--latest")


def main():
    release(os.environ["RELEASE_TAG"], os.environ["SOURCE_SHA"], os.environ["PUBLICATION"],
            Path("dist"), Path("downloaded-release"))


if __name__ == "__main__":
    main()
