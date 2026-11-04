#!/usr/bin/env python3
"""Validate native artifacts and retain exact-byte, same-source provenance."""
import argparse
import hashlib
import json
import platform
import plistlib
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tarfile

PRODUCT = "ULID.bundle"
COMMON = {"Contents/Info.plist", "Contents/Resources/manifest.json",
          "Contents/Resources/constants.xlf", "Contents/Resources/LICENSE",
          "Contents/Resources/LICENSE-4D", "Contents/Resources/LICENSE-suyash"}
BINARIES = {"macos": "Contents/MacOS/ULID",
            "windows": "Contents/Windows64/ULID.4DX"}
COMMAND_SYNTAX = (
    "ULID from UUID(&T):T",
    "ULID to UUID(&T):T",
    "Generate ULID(&T):T",
    "ULID Get timestamp(&T):T",
    "ULID Set timestamp(&T;&T):T",
    "ULID Generate(&T):T",
    "ULID To blob(&T;&T):O",
    "ULID From blob(&O;&T):T",
    "ULID Timestamp(&T;&T):8",
    "ULID Is valid(&T):L",
)


def portable(path):
    return path.as_posix()


def inventory(root):
    files = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"Symlinks are not allowed: {path}")
        if path.is_file():
            files[portable(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return files


def revision(value):
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise ValueError("Source revision must be a full lowercase Git SHA")
    return value


def validate_pe(path):
    data = path.read_bytes()
    if data[:2] != b"MZ":
        raise ValueError("Not a PE binary")
    pe = struct.unpack_from("<I", data, 0x3c)[0]
    if data[pe:pe + 4] != b"PE\0\0":
        raise ValueError("Invalid PE signature")
    machine, sections = struct.unpack_from("<HH", data, pe + 4)
    optional_size = struct.unpack_from("<H", data, pe + 20)[0]
    optional = pe + 24
    if machine != 0x8664 or struct.unpack_from("<H", data, optional)[0] != 0x20b:
        raise ValueError("Windows artifact must be x64 PE32+")
    export_rva, export_size = struct.unpack_from("<II", data, optional + 112)
    if not export_rva or not export_size:
        raise ValueError("Missing PE exports")
    section_start = optional + optional_size

    def offset(rva):
        for i in range(sections):
            entry = section_start + i * 40
            size, start, raw_size, raw = struct.unpack_from("<IIII", data, entry + 8)
            if start <= rva < start + max(size, raw_size):
                result = raw + rva - start
                if result >= len(data):
                    break
                return result
        raise ValueError("Invalid PE RVA")

    exports = offset(export_rva)
    count = struct.unpack_from("<I", data, exports + 24)[0]
    names = offset(struct.unpack_from("<I", data, exports + 32)[0])
    found = set()
    for i in range(count):
        name = offset(struct.unpack_from("<I", data, names + 4 * i)[0])
        end = data.index(b"\0", name)
        found.add(data[name:end].decode("ascii"))
    if "FourDPackex" not in found:
        raise ValueError("Missing FourDPackex export")


def validate_manifest(data):
    if not isinstance(data, dict) or data.get("name") != "ULID" or data.get("id") != 20000:
        raise ValueError("Invalid ULID manifest identity")
    commands = data.get("commands")
    if not isinstance(commands, list) or len(commands) != len(COMMAND_SYNTAX):
        raise ValueError("Manifest must contain exactly command IDs 1-10")
    # Classic 4D command IDs are the one-based positions in this array.
    for command_id, (command, syntax) in enumerate(zip(commands, COMMAND_SYNTAX), 1):
        if (not isinstance(command, dict) or command.get("syntax") != syntax
                or command.get("theme") != "ULID" or command.get("threadSafe") is not True):
            raise ValueError(f"Manifest command ID {command_id} does not match the ABI contract")


def validate(root, targets):
    files = inventory(root)
    required = COMMON | {BINARIES[target] for target in targets}
    if not required <= files.keys():
        raise ValueError(f"Missing package files: {required - files.keys()}")
    allowed = required | {name for name in files if name.startswith("Contents/_CodeSignature/")}
    if files.keys() - allowed:
        raise ValueError(f"Unexpected package files: {files.keys() - allowed}")
    info = plistlib.loads((root / "Contents/Info.plist").read_bytes())
    if info.get("CFBundleExecutable") != "ULID" or info.get("CFBundlePackageType") != "BNDL":
        raise ValueError("Invalid bundle metadata")
    validate_manifest(json.loads((root / "Contents/Resources/manifest.json").read_bytes()))
    if "windows" in targets:
        validate_pe(root / BINARIES["windows"])
    if "macos" in targets:
        binary = root / BINARIES["macos"]
        arches = subprocess.check_output(["lipo", "-archs", str(binary)], text=True).split()
        if set(arches) != {"arm64", "x86_64"}:
            raise ValueError(f"Expected universal macOS binary, got {arches}")
        for arch in arches:
            symbols = subprocess.check_output(
                ["nm", "-arch", arch, "-gU", str(binary)], text=True)
            if not re.search(r"\b_FourDPackex$", symbols, re.MULTILINE):
                raise ValueError(f"Missing FourDPackex export for {arch}")
    return files


def record(root, target, sha, output):
    revision(sha)
    if subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip() != sha:
        raise ValueError("Build checkout does not match source revision")
    subprocess.run(["git", "diff", "--exit-code", "--quiet", sha, "--"], check=True)
    # Export repository metadata as immutable object bytes, avoiding Windows CRLF conversion.
    for destination, source in (
        ("Contents/Info.plist", "Info.plist"),
        ("Contents/Resources/manifest.json", "manifest.json"),
        ("Contents/Resources/constants.xlf", "constants.xlf"),
        ("Contents/Resources/LICENSE", "LICENSE"),
        ("Contents/Resources/LICENSE-4D", "4D Plugin API/LICENSE"),
        ("Contents/Resources/LICENSE-suyash", "suyash/LICENSE"),
    ):
        (root / destination).write_bytes(subprocess.check_output(["git", "show", f"{sha}:{source}"]))
    data = {
        "schema": 1, "source": sha, "target": target,
        "architectures": ["arm64", "x86_64"] if target == "macos" else ["x86_64"],
        "signing": "pre-signing; Windows unsigned",
        "host": platform.platform(),
        "cmake": subprocess.check_output(["cmake", "--version"], text=True).splitlines()[0],
        "compiler": [p.read_text() for p in Path("build/CMakeFiles").glob("*/CMakeCXXCompiler.cmake")],
        "files": validate(root, [target]),
    }
    if not data["compiler"]:
        raise ValueError("Missing CMake compiler provenance")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(data, indent=2) + "\n")


def verify(root, manifest, sha, target):
    data = json.loads(manifest.read_text())
    if (data.get("schema"), data.get("source"), data.get("target")) != (1, revision(sha), target):
        raise ValueError("Artifact source/target provenance mismatch")
    expected_arches = ["arm64", "x86_64"] if target == "macos" else ["x86_64"]
    if data.get("architectures") != expected_arches:
        raise ValueError("Architecture provenance mismatch")
    if not data.get("cmake") or not data.get("compiler") or not data.get("host"):
        raise ValueError("Missing build toolchain provenance")
    if any("\\" in key or key.startswith("/") or ".." in key.split("/") for key in data["files"]):
        raise ValueError("Nonportable provenance path")
    if inventory(root) != data["files"]:
        raise ValueError("Exact-byte artifact inventory mismatch")
    validate(root, [target])
    return data


def unpack(archive, destination):
    if destination.exists():
        raise ValueError("Extraction destination must not exist")
    with tarfile.open(archive) as tar:
        for member in tar.getmembers():
            parts = member.name.split("/")
            if (member.name.startswith("/") or "\\" in member.name or ".." in parts
                    or not (member.isfile() or member.isdir())):
                raise ValueError("Unsafe artifact archive")
        destination.mkdir(parents=True)
        tar.extractall(destination, filter="data")


def assemble(inputs, output, sha):
    manifests = {}
    for target in BINARIES:
        source = inputs / target
        manifests[target] = verify(source / PRODUCT, source / "provenance.json", sha, target)
    for common in COMMON:
        if manifests["macos"]["files"][common] != manifests["windows"]["files"][common]:
            raise ValueError(f"Cross-platform metadata differs: {common}")
    if output.exists():
        raise ValueError("Package destination must not exist")
    shutil.copytree(inputs / "macos" / PRODUCT, output)
    windows = output / BINARIES["windows"]
    windows.parent.mkdir(parents=True)
    shutil.copy2(inputs / "windows" / PRODUCT / BINARIES["windows"], windows)
    (output / BINARIES["macos"]).chmod(0o755)
    validate(output, BINARIES)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    for command in ("record", "verify"):
        sub = subs.add_parser(command)
        sub.add_argument("--bundle", type=Path, required=True)
        sub.add_argument("--target", choices=BINARIES, required=True)
        sub.add_argument("--sha", required=True)
        sub.add_argument("--manifest", type=Path, required=True)
    sub = subs.add_parser("unpack")
    sub.add_argument("archive", type=Path)
    sub.add_argument("destination", type=Path)
    sub = subs.add_parser("validate")
    sub.add_argument("--bundle", type=Path, required=True)
    sub.add_argument("--target", choices=BINARIES, action="append", required=True)
    sub = subs.add_parser("assemble")
    sub.add_argument("--inputs", type=Path, required=True)
    sub.add_argument("--bundle", type=Path, required=True)
    sub.add_argument("--sha", required=True)
    sub = subs.add_parser("inventory")
    sub.add_argument("root", type=Path)
    sub.add_argument("output", type=Path)
    sub.add_argument("--sha", required=True)
    args = parser.parse_args()
    if args.command == "record":
        record(args.bundle, args.target, args.sha, args.manifest)
    elif args.command == "verify":
        verify(args.bundle, args.manifest, args.sha, args.target)
    elif args.command == "unpack":
        unpack(args.archive, args.destination)
    elif args.command == "validate":
        files = validate(args.bundle, args.target)
        print(f"Validated {len(files)} package files for {', '.join(args.target)}")
    elif args.command == "assemble":
        assemble(args.inputs, args.bundle, args.sha)
    else:
        args.output.write_text(json.dumps(
            {"schema": 1, "source": revision(args.sha), "files": inventory(args.root),
             "windows_signing": "unsigned"}, indent=2) + "\n")


if __name__ == "__main__":
    main()
