import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("host_smoke", ROOT / "scripts/host_smoke.py")
HOST_SMOKE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HOST_SMOKE)


class HostSmokeTests(unittest.TestCase):
    def invoke(self, directory, completed, extra=()):
        report = Path(directory) / "report.json"
        report.write_text('{"success": true}', encoding="utf-8")
        bundle = Path(directory) / "fake.bundle"
        bundle.mkdir()
        args = ["host_smoke", "--runtime", sys.executable, "--report", str(report),
                "--bundle", str(bundle), *extra]
        with patch.object(sys, "argv", args), \
                patch.object(HOST_SMOKE.subprocess, "run", side_effect=completed), \
                contextlib.redirect_stdout(io.StringIO()):
            HOST_SMOKE.main()
        return report

    def test_baseline_has_no_plugins(self):
        def complete(command, **_):
            project = Path(command[-1].split("=", 1)[1]).parent.parent
            self.assertFalse((project / "Plugins").exists())
            (project / "ulid-smoke.json").write_text(
                '{"success": true, "compiled": false}', encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, "", "")

        with tempfile.TemporaryDirectory() as directory:
            report = self.invoke(directory, complete, ["--baseline"])
            self.assertTrue(json.loads(report.read_text())["success"])

    def test_nonzero_exit_rejects_success_report(self):
        def complete(command, **_):
            project = Path(command[-1].split("=", 1)[1]).parent.parent
            (project / "ulid-smoke.json").write_text('{"success": true}', encoding="utf-8")
            return subprocess.CompletedProcess(command, -11, "", "host shutdown failure")

        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(subprocess.CalledProcessError):
                self.invoke(directory, complete, ["--baseline"])
            self.assertFalse((Path(directory) / "report.json").exists())
            diagnostics = list(Path(directory).glob("host-failure-*/runtime-result.json"))
            self.assertEqual(len(diagnostics), 1)
            self.assertEqual(json.loads(diagnostics[0].read_text())["exitCode"], -11)

    def test_missing_report_rejects_zero_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, "exactly one"):
                self.invoke(directory, lambda command, **_: subprocess.CompletedProcess(
                    command, 0, "", ""), ["--baseline"])
            self.assertFalse((Path(directory) / "report.json").exists())

    def test_false_report_rejected(self):
        def complete(command, **_):
            project = Path(command[-1].split("=", 1)[1]).parent.parent
            (project / "ulid-smoke.json").write_text('{"success": false}', encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, "", "")

        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, "smoke failed"):
                self.invoke(directory, complete, ["--baseline"])

    def test_compile_diagnostics_rejected(self):
        def complete(command, **_):
            project = Path(command[-1].split("=", 1)[1]).parent.parent
            (project / "ulid-compile.json").write_text(
                '{"success": true, "errors": [{"message": "warning"}]}', encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, "", "")

        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, "emitted diagnostics"):
                self.invoke(directory, complete, ["--compiled"])

    def test_compiled_mode_required(self):
        def complete(command, **_):
            project = Path(command[-1].split("=", 1)[1]).parent.parent
            if "--startup-method=compile_native" in command:
                (project / "ulid-compile.json").write_text(
                    '{"success": true, "errors": []}', encoding="utf-8")
            else:
                (project / "ulid-smoke.json").write_text(
                    '{"success": true, "compiled": false}', encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, "", "")

        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, "did not execute in compiled mode"):
                self.invoke(directory, complete, ["--compiled"])


if __name__ == "__main__":
    unittest.main()
