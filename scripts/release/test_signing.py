import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import bounded
import notarize
from preflight import SECRETS


SUBMISSION_ID = "12345678-1234-1234-1234-123456789abc"


class BoundedTests(unittest.TestCase):
    def test_completion_and_output_capture(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "response.json"
            bounded.run([sys.executable, "-c", "print('response')"],
                        label="fixture", timeout=5, output=output)
            self.assertEqual(output.read_text().strip(), "response")

    def test_real_timeout_is_bounded_and_does_not_log_secret_arguments(self):
        secret = "fixture-password-do-not-log"
        started = time.monotonic()
        with io.StringIO() as log, contextlib.redirect_stdout(log):
            with self.assertRaisesRegex(bounded.CommandError, "timed out") as error:
                bounded.run([sys.executable, "-c", "import time; time.sleep(30)", secret],
                            label="Sign bundle", timeout=0.1)
            self.assertNotIn(secret, log.getvalue() + str(error.exception))
        self.assertLess(time.monotonic() - started, 5)

    def test_nonzero_and_launch_errors_do_not_include_arguments(self):
        secret = "fixture-password-do-not-log"
        for command in ([sys.executable, "-c", "raise SystemExit(7)", secret],
                        ["missing-signing-command", secret]):
            with self.subTest(command=command), self.assertRaises(bounded.CommandError) as error:
                bounded.run(command, label="Credential setup", timeout=5)
            self.assertNotIn(secret, str(error.exception))

    @unittest.skipUnless(os.name == "posix", "process groups are POSIX")
    def test_timeout_kills_descendants_not_only_parent(self):
        with tempfile.TemporaryDirectory() as temporary:
            marker = Path(temporary) / "orphan-ran"
            child = f"import time; from pathlib import Path; time.sleep(0.7); Path({str(marker)!r}).touch()"
            parent = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',sys.argv[1]]); time.sleep(30)"
            with self.assertRaises(bounded.CommandError):
                bounded.run([sys.executable, "-c", parent, child], label="Process tree", timeout=0.3)
            time.sleep(0.8)
            self.assertFalse(marker.exists())

    @unittest.skipUnless(os.name == "posix", "POSIX signal behavior")
    def test_interruption_kills_command_without_logging_secret_arguments(self):
        with tempfile.TemporaryDirectory() as temporary:
            ready = Path(temporary) / "ready"
            command = [
                sys.executable, str(Path(bounded.__file__)), "--label", "Sign bundle",
                "--timeout", "30", "--", sys.executable, "-c",
                "import sys,time; from pathlib import Path; Path(sys.argv[1]).touch(); time.sleep(30)",
                str(ready), "fixture-password-do-not-log",
            ]
            with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as process:
                try:
                    deadline = time.monotonic() + 10
                    while not ready.exists() and time.monotonic() < deadline:
                        time.sleep(0.02)
                    self.assertTrue(ready.exists())
                    process.terminate()
                    output, error = process.communicate(timeout=5)
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait()
                self.assertNotEqual(process.returncode, 0)
                self.assertIn("interrupted", output)
                self.assertNotIn("fixture-password-do-not-log", output + error)


class NotarizationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.report = Path(self.temporary.name) / "zip-notarization.json"
        self.commands = []
        self.statuses = iter(["Accepted"])
        self.clock = 0
        self.failure = None
        self.addCleanup(patch.stopall)
        patch("notarize.run", side_effect=self.run_command).start()
        patch("notarize.time.monotonic", side_effect=lambda: self.clock).start()
        patch("notarize.time.sleep", side_effect=self.sleep).start()

    def sleep(self, duration):
        self.clock += duration

    def run_command(self, command, *, label, timeout, output):
        self.assertGreater(timeout, 0)
        self.assertLessEqual(timeout, 180 if command[2] == "submit" else 60)
        self.assertIn("--keychain-profile", command)
        self.assertNotIn("--password", command)
        self.assertNotIn("--wait", command)
        self.commands.append(command[2])
        if command[2] == self.failure:
            raise bounded.CommandError(f"{label}: timed out; publication blocked")
        response = {"id": SUBMISSION_ID}
        if command[2] == "info":
            response["status"] = next(self.statuses)
        elif command[2] == "log":
            response["issues"] = [{"message": "fixture diagnostic"}]
        Path(output).write_text(json.dumps(response))

    def notarize(self, **kwargs):
        notarize.notarize("fixture.zip", self.report, "fixture.keychain", **kwargs)

    def test_pending_then_accepted_retains_id_status_and_diagnostics(self):
        self.statuses = iter(["In Progress", "In Progress", "Accepted"])
        with io.StringIO() as log, contextlib.redirect_stdout(log):
            self.notarize()
            self.assertIn(SUBMISSION_ID, log.getvalue())
            self.assertIn("In Progress", log.getvalue())
            self.assertIn("Accepted", log.getvalue())
        self.assertEqual(self.commands, ["submit", "info", "info", "info", "log"])
        self.assertEqual(json.loads(self.report.read_text())["status"], "Accepted")
        self.assertTrue(self.report.with_name("zip-notarization-submission.json").exists())
        self.assertTrue(self.report.with_name("zip-notarization-log.json").exists())

    def test_invalid_and_rejected_fail_with_diagnostics(self):
        for status in ("Invalid", "Rejected"):
            self.commands.clear()
            self.statuses = iter([status])
            with self.subTest(status=status), self.assertRaisesRegex(bounded.CommandError, status):
                self.notarize()
            self.assertEqual(self.commands, ["submit", "info", "log"])
            self.assertEqual(json.loads(self.report.read_text())["status"], status)
            self.assertTrue(self.report.with_name("zip-notarization-log.json").exists())

    def test_pending_deadline_fails_and_keeps_last_status_and_submission(self):
        self.statuses = iter(["In Progress"] * 10)
        # Simulate the real runner refusing to start after the deadline.
        original = self.run_command

        def run(*args, **kwargs):
            if kwargs["timeout"] <= 0:
                raise bounded.CommandError("deadline expired; publication blocked")
            return original(*args, **kwargs)

        with patch("notarize.run", side_effect=run):
            with self.assertRaisesRegex(bounded.CommandError, "deadline expired"):
                self.notarize(timeout=20, interval=15)
        self.assertEqual(self.clock, 20)
        self.assertEqual(self.commands, ["submit", "info", "info"])
        self.assertEqual(json.loads(self.report.read_text())["status"], "In Progress")
        self.assertEqual(json.loads(self.report.with_name(
            "zip-notarization-submission.json").read_text())["id"], SUBMISSION_ID)

    def test_submit_info_or_log_timeout_fails_closed(self):
        for stage in ("submit", "info", "log"):
            self.commands.clear()
            self.statuses = iter(["Accepted"])
            self.failure = stage
            with self.subTest(stage=stage), self.assertRaisesRegex(bounded.CommandError, "timed out"):
                self.notarize()
            self.assertEqual(self.commands[-1], stage)

    def test_unknown_status_or_missing_id_fails_closed(self):
        self.statuses = iter(["Unknown"])
        with self.assertRaisesRegex(bounded.CommandError, "unexpected status"):
            self.notarize()
        self.assertNotIn("log", self.commands)
        with patch("notarize.read_response", return_value={"status": "Accepted"}):
            with self.assertRaisesRegex(bounded.CommandError, "submission ID"):
                self.notarize()

    def test_malformed_or_mismatched_response_fails_closed(self):
        for response, message in (([], "invalid response"),
                                  ({"id": "other", "status": "Accepted"}, "ID mismatch")):
            with self.subTest(response=response):
                self.statuses = iter(["Accepted"])
                real_read = notarize.read_response

                def read(path):
                    if path.name.endswith("-response.json"):
                        path.write_text(json.dumps(response))
                    return real_read(path)

                with patch("notarize.read_response", side_effect=read):
                    with self.assertRaisesRegex(bounded.CommandError, message):
                        self.notarize()


@unittest.skipUnless(os.name == "posix", "sign.sh requires a POSIX host")
class SigningScriptTests(unittest.TestCase):
    def test_timeouts_rejection_and_acceptance_run_real_shell_gates_and_cleanup(self):
        tools = """import json, os, sys, time
from pathlib import Path
tool = Path(sys.argv[0]).name
args = sys.argv[1:]
mode = os.environ["FIXTURE_MODE"]
with open("events.txt", "a") as events:
    events.write(tool + " " + args[0] + "\\n")
if tool == "security":
    if args[0] == "create-keychain":
        Path(args[-1]).touch()
    elif args[0] == "delete-keychain":
        if mode == "invalid-cleanup-failure":
            sys.exit(23)
        Path(args[-1]).unlink()
    elif args[0] == "find-identity":
        print('A' * 40 + ' "Developer ID Application: Fixture (A123456789)"')
elif tool == "codesign":
    if "--force" in args and mode == "sign-timeout":
        time.sleep(30)
    if "-d" in args:
        print("TeamIdentifier=A123456789\\nAuthority=Developer ID Application: Fixture\\nTimestamp=fixture\\nCodeDirectory fixture flags=runtime", file=sys.stderr)
elif tool == "xcrun" and args[0] == "notarytool" and args[1] != "store-credentials":
    response = {"id": "12345678-1234-1234-1234-123456789abc"}
    if args[1] == "info":
        response["status"] = {"pending": "In Progress", "invalid": "Invalid", "invalid-cleanup-failure": "Invalid"}.get(mode, "Accepted")
    print(json.dumps(response))
elif tool == "hdiutil":
    # Stop at an observable post-ZIP-acceptance boundary without real packaging.
    sys.exit(17)
"""
        launcher = """import os, subprocess, sys
args = sys.argv[1:]
if args[0].endswith("bounded.py") and "Sign bundle with secure timestamp" in args and os.environ["FIXTURE_MODE"] == "sign-timeout":
    args[args.index("--timeout") + 1] = "1"
if args[0].endswith("notarize.py"):
    sys.path.insert(0, "scripts/release")
    import notarize
    from bounded import CommandError
    try:
        notarize.notarize(*args[1:], timeout=3, interval=0.1)
    except CommandError as error:
        print("ERROR", error)
        sys.exit(1)
else:
    sys.exit(subprocess.call([sys.executable, *args]))
"""
        for mode in ("sign-timeout", "pending", "invalid", "invalid-cleanup-failure", "accepted"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                scripts = root / "scripts/release"
                scripts.mkdir(parents=True)
                for name in ("sign.sh", "bounded.py", "notarize.py", "preflight.py"):
                    shutil.copyfile(Path(__file__).parent / name, scripts / name)
                binaries = root / "bin"
                binaries.mkdir()
                for name, body in (("python3", launcher), *((
                        name, tools) for name in ("security", "codesign", "xcrun", "ditto", "hdiutil"))):
                    path = binaries / name
                    path.write_text(f"#!{sys.executable}\n" + body)
                    path.chmod(0o755)
                environment = {
                    **os.environ,
                    **dict.fromkeys(SECRETS, "fixture-password-do-not-log"),
                    "APPLE_DEVELOPER_ID_CERTIFICATE": "Zml4dHVyZQ==",
                    "NOTARYTOOL_TEAM_ID": "A123456789",
                    "RELEASE_TAG": "v1.2.3",
                    "SOURCE_SHA": "a" * 40,
                    "FIXTURE_MODE": mode,
                    "PATH": str(binaries) + os.pathsep + os.environ["PATH"],
                }
                result = subprocess.run(["bash", "scripts/release/sign.sh"], cwd=root,
                                        env=environment, capture_output=True, text=True, timeout=30)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("fixture-password-do-not-log", result.stdout + result.stderr)
                events = (root / "events.txt").read_text()
                self.assertIn("security delete-keychain", events)
                self.assertEqual((root / "release-state/build.keychain-db").exists(),
                                 mode == "invalid-cleanup-failure")
                self.assertFalse((root / "release-state/certificate.p12").exists())
                self.assertFalse((root / "dist/release-provenance.json").exists())
                if mode == "sign-timeout":
                    self.assertIn("Sign bundle with secure timestamp: timed out", result.stdout)
                    self.assertNotIn("ditto ", events)
                elif mode == "accepted":
                    self.assertIn("hdiutil create", events, result.stdout + result.stderr)
                else:
                    self.assertNotIn("hdiutil ", events)
                    report = root / "release-state/zip-notarization.json"
                    self.assertTrue(report.exists(), result.stdout + result.stderr)
                    self.assertEqual(json.loads(report.read_text())["status"],
                                     "In Progress" if mode == "pending" else "Invalid")


if __name__ == "__main__":
    unittest.main()
