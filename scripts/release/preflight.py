#!/usr/bin/env python3
"""Fail before building/signing if release authorization or configuration is incomplete."""
import json
import os
from pathlib import Path
import plistlib
import re
import subprocess
import urllib.error
import urllib.request

SECRETS = (
    "APPLE_DEVELOPER_ID_CERTIFICATE", "APPLE_DEVELOPER_ID_CERTIFICATE_PASSWORD",
    "KEYCHAIN_PASSWORD", "NOTARYTOOL_APPLE_ID", "NOTARYTOOL_TEAM_ID", "NOTARYTOOL_PASSWORD",
)


def validate(env, plist):
    missing = [key for key in SECRETS if not env.get(key)]
    if missing:
        raise ValueError("Missing required secrets: " + ", ".join(missing))
    if env.get("PUBLICATION") != "create-draft":
        raise ValueError("Explicit create-draft authorization required")
    tag = env.get("RELEASE_TAG", "")
    if not re.fullmatch(r"v(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)", tag):
        raise ValueError("Tag must be vX.Y.Z")
    if plist.get("CFBundleShortVersionString") != tag[1:]:
        raise ValueError("Tag must match committed Info.plist version")
    if not re.fullmatch(r"[A-Z0-9]{10}", env["NOTARYTOOL_TEAM_ID"]):
        raise ValueError("Invalid expected Developer ID team")
    return tag


def main():
    tag = validate(os.environ, plistlib.loads(Path("Info.plist").read_bytes()))
    sha = os.environ["GITHUB_SHA"]
    actual = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if sha != actual:
        raise ValueError("Checkout does not match the workflow's immutable source SHA")
    base = os.environ["GITHUB_API_URL"] + "/repos/" + os.environ["GITHUB_REPOSITORY"]
    for suffix in (f"/git/ref/tags/{tag}", f"/releases/tags/{tag}"):
        request = urllib.request.Request(base + suffix, headers={
            "Authorization": "Bearer " + os.environ["GH_TOKEN"],
            "Accept": "application/vnd.github+json",
        })
        try:
            with urllib.request.urlopen(request) as response:
                json.load(response)
        except urllib.error.HTTPError as error:
            if error.code == 404:
                continue
            raise
        raise ValueError("Existing tag/release is never overwritten")
    print(f"Preflight passed for {tag} at {sha}; Windows distribution is unsigned.")


if __name__ == "__main__":
    main()
