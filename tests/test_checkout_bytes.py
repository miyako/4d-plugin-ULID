from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CheckoutBytesTests(unittest.TestCase):
    def test_windows_checkout_preserves_provenance_inputs(self):
        inputs = [
            "manifest.json", "constants.xlf", "Info.plist", "LICENSE",
            "4DPlugin-ULID.cpp", "ulid_core.h", "CMakeLists.txt",
            "4D Plugin API/4DPluginAPI.c", "4D Plugin API/LICENSE",
            "suyash/ulid.hh", "suyash/ulid_struct.hh", "suyash/ulid_uint128.hh",
            "suyash/LICENSE",
        ]
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory) / "repository"
            repository.mkdir()
            checkout = Path(directory) / "checkout"
            checkout.mkdir()
            subprocess.run(["git", "init", "-q", str(repository)], check=True,
                           capture_output=True)
            for name in inputs:
                target = repository / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / name, target)
            (repository / ".gitattributes").write_bytes(
                (ROOT / ".gitattributes").read_bytes() + b"\ncontrol.txt text\n")
            (repository / "control.txt").write_bytes(b"conversion control\n")
            git = ["git", "-C", str(repository), "-c", "core.autocrlf=true",
                   "-c", "core.eol=crlf"]
            subprocess.run([*git, "add", "."], check=True, capture_output=True)
            subprocess.run([*git, "checkout-index", "--all", f"--prefix={checkout.as_posix()}/"],
                           check=True, capture_output=True)
            self.assertEqual((checkout / "control.txt").read_bytes(), b"conversion control\r\n")
            for name in inputs:
                self.assertEqual((checkout / name).read_bytes(), (ROOT / name).read_bytes(), name)


if __name__ == "__main__":
    unittest.main()
