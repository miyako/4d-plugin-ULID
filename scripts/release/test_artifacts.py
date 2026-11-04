import io
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import plistlib
import shutil
import stat
import struct
import subprocess
import tarfile
import unittest
from unittest.mock import patch
import uuid

import artifacts
import preflight
import runtime_archive


def manifest_fixture():
    return {
        "name": "ULID", "id": 20000,
        "commands": [{"theme": "ULID", "syntax": syntax, "threadSafe": True}
                     for syntax in artifacts.COMMAND_SYNTAX],
    }


def pe_fixture():
    data = bytearray(1024)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3c, 0x80)
    data[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<HH", data, 0x84, 0x8664, 1)
    struct.pack_into("<H", data, 0x94, 240)
    struct.pack_into("<H", data, 0x98, 0x20b)
    struct.pack_into("<II", data, 0x98 + 112, 0x1000, 100)
    struct.pack_into("<IIII", data, 0x98 + 240 + 8, 512, 0x1000, 512, 512)
    struct.pack_into("<I", data, 512 + 24, 1)
    struct.pack_into("<I", data, 512 + 32, 0x1040)
    struct.pack_into("<I", data, 512 + 64, 0x1050)
    data[592:604] = b"FourDPackex\0"
    return data


class ArtifactTests(unittest.TestCase):
    def setUp(self):
        # Scratch paths stay inside the worktree on every host.
        self.root = Path("release-test-" + uuid.uuid4().hex)
        self.root.mkdir()
        self.addCleanup(self.cleanup)
        self.sha = "a" * 40

    def cleanup(self):
        def writable(function, path, _error):
            os.chmod(path, stat.S_IWRITE)
            function(path)
        shutil.rmtree(self.root, onerror=writable)

    def bundle(self, target):
        root = self.root / target / artifacts.PRODUCT
        for name in artifacts.COMMON | {artifacts.BINARIES[target]}:
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"fixture")
        (root / "Contents/Info.plist").write_bytes(plistlib.dumps({
            "CFBundleExecutable": "ULID", "CFBundlePackageType": "BNDL",
        }))
        (root / "Contents/Resources/manifest.json").write_text(json.dumps(manifest_fixture()))
        if target == "windows":
            (root / artifacts.BINARIES[target]).write_bytes(pe_fixture())
        return root

    def manifest(self, root, target):
        path = root.parent / "provenance.json"
        path.write_text(json.dumps({
            "schema": 1, "source": self.sha, "target": target,
            "architectures": ["x86_64"] if target == "windows" else ["arm64", "x86_64"],
            "cmake": "cmake fixture", "compiler": ["compiler fixture"], "host": "fixture",
            "files": artifacts.inventory(root),
        }))
        return path

    def test_windows_path_serialization(self):
        self.assertEqual(artifacts.portable(PureWindowsPath("Contents/Windows64/ULID.4DX")),
                         "Contents/Windows64/ULID.4DX")

    def test_exact_bytes_and_sha(self):
        root = self.bundle("windows")
        manifest = self.manifest(root, "windows")
        artifacts.verify(root, manifest, self.sha, "windows")
        with self.assertRaises(ValueError):
            artifacts.verify(root, manifest, "b" * 40, "windows")
        (root / "Contents/Resources/constants.xlf").write_bytes(b"fixture\r\n")
        with self.assertRaises(ValueError):
            artifacts.verify(root, manifest, self.sha, "windows")

    def test_extra_missing_nonportable_and_wrong_target(self):
        root = self.bundle("windows")
        manifest = self.manifest(root, "windows")
        data = json.loads(manifest.read_text())
        data["files"]["Contents\\Windows64\\ULID.4DX"] = "0" * 64
        manifest.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "Nonportable"):
            artifacts.verify(root, manifest, self.sha, "windows")
        with self.assertRaises(ValueError):
            artifacts.verify(root, manifest, self.sha, "macos")
        (root / "extra").write_text("extra")
        with self.assertRaisesRegex(ValueError, "Unexpected"):
            artifacts.validate(root, ["windows"])
        (root / "extra").unlink()
        (root / "Contents/Info.plist").unlink()
        with self.assertRaisesRegex(ValueError, "Missing"):
            artifacts.validate(root, ["windows"])

    def test_pe_architecture_and_export(self):
        root = self.bundle("windows")
        binary = root / artifacts.BINARIES["windows"]
        artifacts.validate_pe(binary)
        data = pe_fixture()
        struct.pack_into("<H", data, 0x84, 0xaa64)
        binary.write_bytes(data)
        with self.assertRaisesRegex(ValueError, "x64"):
            artifacts.validate_pe(binary)
        data = pe_fixture().replace(b"FourDPackex", b"WrongExport")
        binary.write_bytes(data)
        with self.assertRaisesRegex(ValueError, "FourDPackex"):
            artifacts.validate_pe(binary)

    @patch("artifacts.subprocess.check_output")
    def test_universal_exports(self, run):
        root = self.bundle("macos")
        run.side_effect = ["x86_64 arm64", "000 T _FourDPackex\n", "000 T _FourDPackex\n"]
        artifacts.validate(root, ["macos"])
        run.side_effect = ["arm64"]
        with self.assertRaisesRegex(ValueError, "universal"):
            artifacts.validate(root, ["macos"])
        run.side_effect = ["x86_64 arm64", "000 T _WrongExport\n"]
        with self.assertRaisesRegex(ValueError, "export"):
            artifacts.validate(root, ["macos"])

    @patch("artifacts.subprocess.check_output")
    def test_assemble_same_commit_metadata_and_permissions(self, run):
        run.side_effect = lambda command, **kwargs: (
            "arm64 x86_64" if command[0] == "lipo" else "000 T _FourDPackex\n")
        for target in artifacts.BINARIES:
            self.manifest(self.bundle(target), target)
        output = self.root / "combined" / artifacts.PRODUCT
        with patch.object(Path, "chmod", autospec=True, wraps=Path.chmod) as chmod:
            artifacts.assemble(self.root, output, self.sha)
            chmod.assert_any_call(output / artifacts.BINARIES["macos"], 0o755)
        (output / artifacts.BINARIES["macos"]).chmod(0o755)
        self.assertEqual(len(artifacts.inventory(output)), 8)
        if os.name != "nt":
            self.assertTrue((output / artifacts.BINARIES["macos"]).stat().st_mode & 0o111)
        with self.assertRaises(ValueError):
            artifacts.assemble(self.root, output, self.sha)
        windows = self.root / "windows" / artifacts.PRODUCT
        (windows / "Contents/Resources/constants.xlf").write_bytes(b"different")
        self.manifest(windows, "windows")
        with self.assertRaisesRegex(ValueError, "metadata differs"):
            artifacts.assemble(self.root, self.root / "other", self.sha)

    def test_archive_roundtrip_and_reject_traversal_links(self):
        for name, kind in (("../escape", tarfile.REGTYPE), ("link", tarfile.SYMTYPE)):
            archive = self.root / "unsafe.tar"
            with tarfile.open(archive, "w") as tar:
                entry = tarfile.TarInfo(name)
                entry.type = kind
                entry.linkname = "target"
                tar.addfile(entry, io.BytesIO())
            with self.assertRaisesRegex(ValueError, "Unsafe"):
                artifacts.unpack(archive, self.root / "extracted")
        archive = self.root / "safe.tar"
        with tarfile.open(archive, "w") as tar:
            entry = tarfile.TarInfo("file")
            entry.size = 3
            tar.addfile(entry, io.BytesIO(b"abc"))
        artifacts.unpack(archive, self.root / "extracted")
        self.assertEqual((self.root / "extracted/file").read_bytes(), b"abc")

    def test_revision(self):
        for value in ("main", "../escape", "a" * 39, "A" * 40):
            with self.assertRaises(ValueError):
                artifacts.revision(value)

    def test_record_immutable_git_bytes_and_dirty_source_rejection(self):
        repository = (self.root / "source").resolve()
        repository.mkdir()
        real_check_output = subprocess.check_output

        def git(*args):
            return subprocess.check_output(["git", *args], cwd=repository,
                                           stderr=subprocess.PIPE).decode().strip()

        git("init", "--quiet")
        git("config", "core.autocrlf", "true")
        git("config", "core.safecrlf", "false")
        (repository / ".gitattributes").write_bytes(
            b'LICENSE -text\n"4D Plugin API/LICENSE" -text\nsuyash/LICENSE -text\n')
        resources = {
            "Info.plist": plistlib.dumps({
                "CFBundleExecutable": "ULID", "CFBundlePackageType": "BNDL",
            }),
            "manifest.json": json.dumps(manifest_fixture(), indent=2).encode() + b"\n",
            "constants.xlf": b"<xliff/>\n",
            "LICENSE": b"Fixture license\r\n",
            "4D Plugin API/LICENSE": b"Fixture 4D SDK license\r\n",
            "suyash/LICENSE": b"Fixture suyash license\r\n",
        }
        for name, value in resources.items():
            (repository / name).parent.mkdir(parents=True, exist_ok=True)
            (repository / name).write_bytes(value)
        git("add", ".")
        git("-c", "commit.gpgsign=false", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
            "commit", "--quiet", "-m", "fixture")
        sha = git("rev-parse", "HEAD")
        for name in resources:
            (repository / name).unlink()
        git("checkout-index", "-f", "-a")
        self.assertIn(b"\r\n", (repository / "constants.xlf").read_bytes())
        bundle = self.bundle("windows").resolve()
        output = bundle.parent / "provenance.json"
        compiler = repository / "build/CMakeFiles/fixture/CMakeCXXCompiler.cmake"
        compiler.parent.mkdir(parents=True)
        compiler.write_text("fixture compiler metadata\n")

        def command(args, **kwargs):
            if args == ["cmake", "--version"]:
                return "cmake fixture\n"
            return real_check_output(args, **kwargs)

        previous = Path.cwd()
        try:
            os.chdir(repository)
            with patch("artifacts.subprocess.check_output", side_effect=command):
                artifacts.record(bundle, "windows", sha, output)
            self.assertEqual((bundle / "Contents/Resources/constants.xlf").read_bytes(),
                             resources["constants.xlf"])
            self.assertEqual((bundle / "Contents/Resources/manifest.json").read_bytes(),
                             resources["manifest.json"])
            self.assertEqual((bundle / "Contents/Resources/LICENSE").read_bytes(),
                             resources["LICENSE"])
            self.assertEqual((bundle / "Contents/Resources/LICENSE-4D").read_bytes(),
                             resources["4D Plugin API/LICENSE"])
            self.assertEqual((bundle / "Contents/Resources/LICENSE-suyash").read_bytes(),
                             resources["suyash/LICENSE"])
            artifacts.verify(bundle, output, sha, "windows")
            (repository / "constants.xlf").write_bytes(b"dirty\n")
            with patch("artifacts.subprocess.check_output", side_effect=command):
                with self.assertRaises(subprocess.CalledProcessError):
                    artifacts.record(bundle, "windows", sha, output)
        finally:
            os.chdir(previous)

    def test_preflight_fails_closed(self):
        env = {key: "configured" for key in preflight.SECRETS}
        env.update(RELEASE_TAG="v1.2.3", PUBLICATION="create-draft", NOTARYTOOL_TEAM_ID="ABC1234567")
        info = {"CFBundleShortVersionString": "1.2.3"}
        self.assertEqual(preflight.validate(env, info), "v1.2.3")
        for key in preflight.SECRETS:
            with self.assertRaisesRegex(ValueError, "Missing"):
                preflight.validate({**env, key: ""}, info)
        for change in ({"PUBLICATION": "none"}, {"RELEASE_TAG": "v1.2.4"},
                       {"RELEASE_TAG": "v1.2.3;exit"}, {"NOTARYTOOL_TEAM_ID": "wrong"}):
            with self.assertRaises(ValueError):
                preflight.validate({**env, **change}, info)

    def test_real_source_manifest_ids_and_abi_contract(self):
        source = Path(__file__).resolve().parents[2] / "manifest.json"
        data = json.loads(source.read_bytes())
        artifacts.validate_manifest(data)
        self.assertEqual(len(data["commands"]), 10)
        self.assertEqual(data["commands"][2]["syntax"], "_o_Generate ULID(&T):T")
        self.assertEqual([command["syntax"] for command in data["commands"][:5]], [
            "ULID from UUID(&T):T", "ULID to UUID(&T):T", "_o_Generate ULID(&T):T",
            "ULID Get timestamp(&T):T", "ULID Set timestamp(&T;&T):T",
        ])
        self.assertEqual(data["commands"][6]["syntax"], "ULID To blob(&T;&T):O")
        self.assertEqual(data["commands"][7]["syntax"], "ULID From blob(&O;&T):T")
        self.assertEqual(data["commands"][8]["syntax"], "ULID Timestamp(&T;&T):8")

    def test_manifest_contract_rejects_reordering_missing_and_wrong_abi(self):
        for index, wrong in (
            (0, "ULID to UUID(&T):T"),
            (2, "Generate ULID(&T):T"),
            (6, "ULID To blob(&T;&T):X"),
            (7, "ULID From blob(&X;&T):T"),
            (8, "ULID Timestamp(&T;&T):R"),
        ):
            data = manifest_fixture()
            data["commands"][index]["syntax"] = wrong
            with self.subTest(command_id=index + 1):
                with self.assertRaisesRegex(ValueError, f"ID {index + 1}"):
                    artifacts.validate_manifest(data)
        data = manifest_fixture()
        data["commands"].pop()
        with self.assertRaisesRegex(ValueError, "IDs 1-10"):
            artifacts.validate_manifest(data)
        data = manifest_fixture()
        data["commands"][5]["threadSafe"] = False
        with self.assertRaisesRegex(ValueError, "ID 6"):
            artifacts.validate_manifest(data)

    def test_pinned_runtime_checksum_path_and_safe_extraction(self):
        archive = self.root / "runtime.tar.xz"
        with tarfile.open(archive, "w:xz") as tar:
            entry = tarfile.TarInfo("tool4d/tool4d.exe")
            entry.mode = 0o755
            entry.size = 3
            tar.addfile(entry, io.BytesIO(b"abc"))
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        destination = self.root / "runtime"
        with self.assertRaisesRegex(ValueError, "checksum"):
            runtime_archive.extract(archive, destination, "0" * 64, "tool4d/tool4d.exe")
        self.assertFalse(destination.exists())
        with self.assertRaisesRegex(ValueError, "relative"):
            runtime_archive.extract(archive, destination, digest, "../outside")
        runtime = runtime_archive.extract(archive, destination, digest, "tool4d/tool4d.exe")
        self.assertEqual(runtime.read_bytes(), b"abc")
        bad_archive = self.root / "unsafe-runtime.tar.xz"
        with tarfile.open(bad_archive, "w:xz") as tar:
            entry = tarfile.TarInfo("../outside")
            tar.addfile(entry, io.BytesIO())
        with self.assertRaises(tarfile.FilterError):
            runtime_archive.extract(bad_archive, self.root / "unsafe-runtime",
                                    hashlib.sha256(bad_archive.read_bytes()).hexdigest(), "tool4d")


if __name__ == "__main__":
    unittest.main()
