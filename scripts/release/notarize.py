"""Submit once, retain the submission ID, and poll notarization with a deadline."""

import argparse
import json
from pathlib import Path
import re
import sys
import time

from bounded import CommandError, progress, run


def read_response(path):
    try:
        response = json.loads(path.read_text())
    except (OSError, ValueError):
        raise CommandError(f"notarization: unreadable JSON response in {path.name}") from None
    if not isinstance(response, dict):
        raise CommandError(f"notarization: invalid response in {path.name}")
    return response


def notarize(artifact, report, keychain, *, timeout=900, interval=15):
    report = Path(report)
    submission = report.with_name(report.stem + "-submission.json")
    deadline = time.monotonic() + timeout
    auth = ["--keychain-profile", "release-profile", "--keychain", str(keychain)]
    label = Path(artifact).suffix.lstrip(".").upper()

    def command(arguments, stage, output, limit=60):
        run(["xcrun", "notarytool", *arguments, *auth, "--output-format", "json"],
            label=f"{label} notarization {stage}", timeout=min(limit, deadline - time.monotonic()),
            output=output)

    command(["submit", str(artifact), "--no-wait"], "submit", submission, 180)
    submission_id = read_response(submission).get("id", "")
    if not isinstance(submission_id, str) or not re.fullmatch(
            r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", submission_id):
        raise CommandError(f"{label} notarization: missing or invalid submission ID")
    progress(f"{label} notarization submission ID: {submission_id}")
    while True:
        latest = report.with_name(report.stem + "-response.json")
        command(["info", submission_id], f"status {submission_id}", latest)
        response = read_response(latest)
        if response.get("id") != submission_id:
            raise CommandError(f"{label} notarization: response submission ID mismatch")
        status = response.get("status")
        if status not in ("Accepted", "In Progress", "Invalid", "Rejected"):
            raise CommandError(f"{label} notarization: unexpected status; inspect {report.name}")
        latest.replace(report)
        progress(f"{label} notarization {submission_id}: {status}")
        if status in ("Accepted", "Invalid", "Rejected"):
            # Keep Apple's full diagnostics, but never dump responses/credentials into logs.
            diagnostics = report.with_name(report.stem + "-log.json")
            command(["log", submission_id], f"diagnostics {submission_id}", diagnostics)
            read_response(diagnostics)
            if status != "Accepted":
                raise CommandError(f"{label} notarization {submission_id}: {status}; publication blocked")
            return
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise CommandError(
                f"{label} notarization {submission_id}: timed out pending acceptance; publication blocked")
        time.sleep(min(interval, remaining))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path)
    parser.add_argument("report", type=Path)
    parser.add_argument("keychain", type=Path)
    args = parser.parse_args()
    try:
        notarize(args.artifact, args.report, args.keychain)
    except CommandError as error:
        print(f"ERROR {error}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
