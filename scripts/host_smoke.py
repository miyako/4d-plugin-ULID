#!/usr/bin/env python3
"""Run the real 4D source smoke method with an isolated project and fresh bundle."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", required=True, type=Path)
    parser.add_argument("--bundle", type=Path, default=Path("build/package/ULID.bundle"))
    parser.add_argument("--report", type=Path, default=Path("build/host-report.json"))
    parser.add_argument("--compiled", action="store_true",
                        help="Require a clean Compile project report, then run in compiled mode")
    parser.add_argument("--baseline", action="store_true",
                        help="Run a minimal source-only control with no Plugins directory")
    args = parser.parse_args()
    if args.baseline and args.compiled:
        parser.error("--baseline is a source-only no-plug-in control")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.unlink(missing_ok=True)
    args.report.with_suffix(".compile.json").unlink(missing_ok=True)
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="ulid-host-") as directory:
        project = Path(directory)
        source = root / ("tests/host-baseline/Project" if args.baseline else "test/Project")
        shutil.copytree(source, project / "Project")
        # A stale catalog must not hide a new method or an old command signature.
        (project / "Project/Sources/catalog.4DCatalog").unlink(missing_ok=True)
        if not args.baseline:
            shutil.copytree(args.bundle, project / "Plugins/ULID.bundle")
        project_file = "baseline.4DProject" if args.baseline else "test.4DProject"
        def run(method, opening_mode):
            completed = subprocess.run(
                [str(args.runtime.resolve()), "--dataless", "--skip-onstartup",
                 f"--startup-method={method}", f"--opening-mode={opening_mode}",
                 f"--project={project / 'Project' / project_file}"],
                capture_output=True, text=True, timeout=120,
            )
            print(completed.stdout, end="")
            print(completed.stderr, end="")
            if completed.returncode != 0:
                diagnostics = Path(tempfile.mkdtemp(prefix="host-failure-", dir=args.report.parent))
                shutil.copytree(project, diagnostics, dirs_exist_ok=True)
                (diagnostics / "runtime-result.json").write_text(json.dumps({
                    "command": completed.args, "exitCode": completed.returncode,
                    "stdout": completed.stdout, "stderr": completed.stderr,
                }, indent=2) + "\n", encoding="utf-8")
                print(f"Preserved failed host project at {diagnostics}")
                completed.check_returncode()

        if args.compiled:
            run("compile_native", "interpreted")
            compile_reports = list(project.rglob("ulid-compile.json"))
            if len(compile_reports) != 1:
                raise RuntimeError("4D did not produce exactly one structured compile report")
            compile_report = json.loads(compile_reports[0].read_text(encoding="utf-8-sig"))
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.with_suffix(".compile.json").write_text(
                json.dumps(compile_report, indent=2) + "\n", encoding="utf-8")
            if compile_report.get("success") is not True or compile_report.get("errors"):
                raise RuntimeError(f"4D compilation failed or emitted diagnostics: {compile_report}")
        run("test_native", "compiled" if args.compiled else "interpreted")
        reports = list(project.rglob("ulid-smoke.json"))
        if len(reports) != 1:
            raise RuntimeError("4D did not produce exactly one structured smoke report")
        report = json.loads(reports[0].read_text(encoding="utf-8-sig"))
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        if report.get("success") is not True:
            raise RuntimeError(f"4D smoke failed: {report}")
        if args.compiled and report.get("compiled") is not True:
            raise RuntimeError("4D did not execute in compiled mode")
        print(json.dumps(report))


if __name__ == "__main__":
    main()
