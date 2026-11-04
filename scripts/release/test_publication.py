import hashlib
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import publication


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=".")
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.dist = root / "dist"
        self.dist.mkdir()
        self.downloaded = root / "downloaded"
        self.sha = "a" * 40
        self.assets = {
            "ULID-1.2.3.zip": b"final signed zip",
            "ULID-1.2.3.dmg": b"final signed and stapled dmg",
            "release-provenance.json": b'{"source":"' + self.sha.encode() + b'"}',
        }
        self.assets["SHA256SUMS"] = "".join(
            f"{hashlib.sha256(data).hexdigest()}  ./{name}\n"
            for name, data in self.assets.items()).encode()
        for name, data in self.assets.items():
            (self.dist / name).write_bytes(data)
        self.events = []
        self.commands = []
        self.failed_command = None
        self.mutate_download = lambda: None
        self.draft = False
        self.uploaded = False
        self.public = False
        self.verified = False
        self.addCleanup(patch.stopall)
        patch("publication.subprocess.run", side_effect=self.gh).start()
        real_verify = publication.verify_download

        def verify(expected, downloaded):
            self.events.append("verify")
            real_verify(expected, downloaded)
            self.verified = True

        patch("publication.verify_download", side_effect=verify).start()

    def gh(self, command, *, check):
        self.assertTrue(check)
        self.assertEqual(command[:2], ["gh", "release"])
        self.assertEqual(command[3], "v1.2.3")
        action = command[2]
        self.events.append(action)
        self.commands.append(command)
        if action == self.failed_command:
            raise subprocess.CalledProcessError(1, command)
        if action == "create":
            self.assertIn("--draft", command)
            self.assertIn("--prerelease=false", command)
            self.assertIn("--latest=false", command)
            self.assertEqual(command[command.index("--target") + 1], self.sha)
            self.assertIn("UNSIGNED", command[-1])
            self.draft = True
        elif action == "upload":
            self.assertTrue(self.draft)
            self.assertNotIn("--clobber", command)
            self.assertEqual({Path(name).name for name in command[4:]}, set(self.assets))
            self.uploaded = True
        elif action == "download":
            self.assertTrue(self.draft and self.uploaded)
            for name in self.assets:
                (self.downloaded / name).write_bytes((self.dist / name).read_bytes())
            self.mutate_download()
        elif action == "edit":
            self.assertTrue(self.draft and self.verified)
            self.assertEqual(command[4:], ["--draft=false", "--prerelease=false", "--latest"])
            self.public = True
            self.draft = False
        else:
            self.fail(f"Unexpected release operation: {action}")

    def release(self, mode="publish"):
        publication.release("v1.2.3", self.sha, mode, self.dist, self.downloaded)

    def test_publish_only_after_exact_download_and_checksum_verification(self):
        self.release()
        self.assertEqual(self.events, ["create", "upload", "download", "verify", "edit"])
        self.assertTrue(self.public)
        self.assertFalse(self.draft)

    def test_create_draft_runs_same_verification_but_never_publishes(self):
        self.release("create-draft")
        self.assertEqual(self.events, ["create", "upload", "download", "verify"])
        self.assertTrue(self.draft)
        self.assertFalse(self.public)

    def test_no_authorization_has_no_effects(self):
        for mode in ("none", "", "invalid", None):
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, "authorization"):
                self.release(mode)
        self.assertEqual(self.events, [])
        self.assertFalse(self.downloaded.exists())

    def test_create_upload_and_download_failures_never_publish(self):
        for action in ("create", "upload", "download"):
            with self.subTest(action=action):
                if self.downloaded.exists():
                    self.downloaded.rmdir()
                self.failed_command = action
                self.events.clear()
                with self.assertRaises(subprocess.CalledProcessError):
                    self.release()
                self.assertNotIn("edit", self.events)
                self.assertNotIn("verify", self.events)
                self.assertFalse(self.public)
                if action != "create":
                    self.assertTrue(self.draft)

    def test_changed_missing_extra_and_checksum_assets_leave_draft(self):
        mutations = (
            lambda: (self.downloaded / "ULID-1.2.3.zip").write_bytes(b"corrupted"),
            lambda: (self.downloaded / "ULID-1.2.3.dmg").unlink(),
            lambda: (self.downloaded / "unexpected").write_bytes(b"extra"),
            lambda: (self.downloaded / "SHA256SUMS").write_bytes(b"replaced checksum"),
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                if self.downloaded.exists():
                    for path in self.downloaded.iterdir():
                        path.unlink()
                    self.downloaded.rmdir()
                self.mutate_download = mutation
                self.events.clear()
                with self.assertRaisesRegex(ValueError, "Draft assets differ"):
                    self.release()
                self.assertEqual(self.events, ["create", "upload", "download", "verify"])
                self.assertTrue(self.draft)
                self.assertFalse(self.public)

    def test_invalid_final_checksums_fail_before_draft_creation(self):
        (self.dist / "ULID-1.2.3.zip").write_bytes(b"changed after hashing")
        with self.assertRaisesRegex(ValueError, "checksums"):
            self.release()
        self.assertEqual(self.events, [])

    def test_download_checksum_gate_failure_never_publishes(self):
        real_verify = publication.verify_checksums

        def checksums(assets):
            if "download" in self.events:
                raise ValueError("Downloaded checksum verification failed")
            real_verify(assets)

        with patch("publication.verify_checksums", side_effect=checksums):
            with self.assertRaisesRegex(ValueError, "Downloaded checksum"):
                self.release()
        self.assertEqual(self.events, ["create", "upload", "download", "verify"])
        self.assertTrue(self.draft)
        self.assertFalse(self.public)

    def test_checksum_inventory_rejects_missing_extra_duplicate_and_invalid_entries(self):
        sums = self.assets["SHA256SUMS"]
        for invalid in (
            b"", b"invalid\n", sums + sums.splitlines(keepends=True)[0],
            sums + b"0" * 64 + b"  ./missing.zip\n",
            sums.replace(b"./ULID-1.2.3.zip", b"../ULID-1.2.3.zip"),
        ):
            with self.subTest(checksums=invalid), self.assertRaises(ValueError):
                publication.verify_checksums({**self.assets, "SHA256SUMS": invalid})


if __name__ == "__main__":
    unittest.main()
