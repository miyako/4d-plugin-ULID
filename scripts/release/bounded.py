"""Bound external signing commands without logging their credential arguments."""

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


class CommandError(RuntimeError):
    pass


def progress(message):
    print(f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} {message}", flush=True)


def run(command, *, label, timeout, output=None):
    if timeout <= 0:
        raise CommandError(f"{label}: deadline expired")
    progress(f"START {label} (limit {timeout:g}s)")
    started = time.monotonic()
    stream = None

    def interrupted(signum, frame):
        raise CommandError(f"{label}: interrupted; publication blocked")

    handlers = {sig: signal.signal(sig, interrupted) for sig in (signal.SIGTERM, signal.SIGINT)}
    try:
        stream = Path(output).open("w") if output else None
        with subprocess.Popen(command, stdout=stream, start_new_session=os.name == "posix") as process:
            try:
                status = process.wait(timeout=timeout)
            except (subprocess.TimeoutExpired, CommandError):
                if os.name == "posix":
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass  # The command exited between the timeout/signal and cleanup.
                else:
                    process.kill()
                process.wait()
                raise
        if status:
            raise CommandError(f"{label}: failed (exit {status})")
    except subprocess.TimeoutExpired:
        raise CommandError(f"{label}: timed out after {timeout:g}s; publication blocked") from None
    except OSError:
        raise CommandError(f"{label}: could not start or save command output") from None
    finally:
        for sig, handler in handlers.items():
            signal.signal(sig, handler)
        if stream:
            stream.close()
    progress(f"DONE {label} ({time.monotonic() - started:.1f}s)")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True)
    parser.add_argument("--timeout", type=float, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command
    if command[:1] == ["--"]:
        command = command[1:]
    if not command:
        parser.error("command required")

    try:
        run(command, label=args.label, timeout=args.timeout, output=args.output)
    except CommandError as error:
        print(f"ERROR {error}", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
