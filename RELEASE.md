# Native CI and signed draft releases

## Read-only validation

`Native CI` runs on branch pushes and pull requests with `contents: read`, no
signing secrets, no persisted checkout credentials, and no tag/release mutation.
Its reusable `native-build.yml` is also the release build path. External actions
are pinned to immutable commits. macOS builds a universal `arm64;x86_64` plugin
(deployment target 11.5); Windows builds x64. CTest runs the native test
executables on each runner's host architecture, not under 4D or across both
macOS slices. Architecture/export checks inspect both macOS slices. Windows
checks the PE32+ x64 header and named `FourDPackex` export.

The CMake build must stage exactly:

```
build/package/ULID.bundle/Contents/
  Info.plist
  MacOS/ULID                 # macOS job
  Windows64/ULID.4DX         # Windows job
  Resources/manifest.json
  Resources/constants.xlf
  Resources/LICENSE
  Resources/LICENSE-4D
  Resources/LICENSE-suyash
```

Configure with `cmake -S . -B build -DCMAKE_BUILD_TYPE=Release`, build with
`cmake --build build --config Release`, and test with
`ctest --test-dir build -C Release --output-on-failure`.
CI additionally selects Windows x64, macOS universal architectures, and fails
when no tests were discovered.

The [tutorial's example CI](https://github.com/miyako/4d-plugin-tutorial/blob/example/.github/workflows/test.yml)
provided the native macOS/Windows matrix pattern. Unlike its moving `latest`
tool4d download, this pipeline exercises the repository's CTest targets without
claiming a 4D-host integration test.

`scripts/release/artifacts.py` records the full source SHA, target, architectures,
host, CMake/compiler metadata and SHA-256 of exact native artifact bytes. Paths
are forward-slash relative paths on every OS. Repository resource bytes are
exported from the immutable Git object before hashing to avoid Windows checkout
newline conversion. This preserves existing CRLF object bytes as CRLF; it does
not arbitrarily normalize resource/license content. Per-platform tar archives
preserve executable permissions.
The same-run packaging job rejects mixed commits, wrong targets, changed bytes,
unexpected/missing files and mismatched resource metadata before merging.
The project, SDK and suyash license files are required resources and are exported
from the same immutable repository snapshot. See `THIRD_PARTY.md` for upstream
provenance and its explicitly documented SDK-baseline limitation.
The actual source and packaged manifest are checked against all ten ordered
command IDs, preserving the original five signatures and requiring classic BLOB
`&O`/`:O` and the `PA_ReturnDouble` result token `:8`. A fixture-only check is
not sufficient: the Python suite also reads the repository's real manifest.
Native manifests are explicitly **pre-signing provenance**, not signed-byte hashes.
This establishes source-pinned provenance, not byte-for-byte reproducible builds
across different compiler/SDK versions.

Run tooling regressions independently:

```
python3 -m unittest discover -s scripts/release -p 'test_*.py' -v
```

### Local artifact commands

Validate the current staged macOS bundle, including its real manifest ABI:

```
python3 scripts/release/artifacts.py validate --bundle build/package/ULID.bundle --target macos
```

After committing all tracked edits, create and verify native provenance. The
record command deliberately rejects a dirty tracked checkout; do not bypass it
or discard unrelated edits. Run these from the repository root after the CMake
build, keeping the artifact tar outside `build/package`:

```
SHA=$(git rev-parse HEAD)
python3 scripts/release/artifacts.py record --bundle build/package/ULID.bundle --target macos --sha "$SHA" --manifest build/package/provenance.json
python3 scripts/release/artifacts.py verify --bundle build/package/ULID.bundle --target macos --sha "$SHA" --manifest build/package/provenance.json
python3 -c "import tarfile; t=tarfile.open('build/native.tar','w'); t.add('build/package/ULID.bundle',arcname='ULID.bundle'); t.add('build/package/provenance.json',arcname='provenance.json'); t.close()"
```

To reproduce the **actual same-run** handoff locally without dispatching
anything, replace `RUN_ID` with an already completed native CI/release run ID.
Both archives must come from that one run, not a local macOS build combined with
a different Windows run. The extraction and package destinations must not
already exist:

```
RUN_ID=123456789
SHA=$(gh run view "$RUN_ID" --json headSha --jq .headSha)
gh run download "$RUN_ID" --pattern 'native-*' --dir build/handoff/downloads
python3 scripts/release/artifacts.py unpack build/handoff/downloads/native-macos/native.tar build/handoff/inputs/macos
python3 scripts/release/artifacts.py unpack build/handoff/downloads/native-windows/native.tar build/handoff/inputs/windows
python3 scripts/release/artifacts.py assemble --inputs build/handoff/inputs --bundle build/handoff/package/ULID.bundle --sha "$SHA"
python3 scripts/release/artifacts.py validate --bundle build/handoff/package/ULID.bundle --target macos --target windows
python3 scripts/release/artifacts.py inventory build/handoff/package build/handoff/package-provenance.json --sha "$SHA"
```

These are unsigned/pre-signing artifact checks. They do not execute the manual
signing/release workflow.

## Manual release authorization

No tag push, PR, branch push or version bump initiates signing or publication.
Only dispatch `Signed draft release` manually, selecting the reviewed source ref,
a **new** `vX.Y.Z` tag matching committed `Info.plist`, and
`publication: create-draft`. The default `none` fails preflight. The workflow
uses the immutable SHA selected by that dispatch for every build and the draft
release's target; existing tags/releases are never overwritten.

Configure the GitHub `release` environment with required reviewers and suitable
branch/tag restrictions before use. The workflow cannot configure those
repository protections. Both preflight and signing use this environment.
Preserved secret names (environment or repository secrets):

| Secret | Purpose |
| --- | --- |
| `APPLE_DEVELOPER_ID_CERTIFICATE` | Base64 PKCS#12 containing Developer ID Application certificate/private key |
| `APPLE_DEVELOPER_ID_CERTIFICATE_PASSWORD` | PKCS#12 import password |
| `KEYCHAIN_PASSWORD` | Password for the isolated, short-lived signing keychain |
| `NOTARYTOOL_APPLE_ID` | Apple account authorized for notarization |
| `NOTARYTOOL_TEAM_ID` | Expected ten-character Developer ID team; identity and signatures must match |
| `NOTARYTOOL_PASSWORD` | App-specific password for notarization |

Every secret is mandatory and checked without logging its value before builds.
The signing job requires exactly one Developer ID Application identity for the
expected team, secure timestamps and hardened runtime. It signs the code bundle
(not arbitrary resource files), verifies its signature, notarizes the ZIP with an
explicit `Accepted` response, signs the DMG container separately, requires its
own notarization `Accepted`, staples and validates the DMG ticket, and performs
strict container signature and Gatekeeper `spctl --type open` assessment.
The ZIP is not stapled: a plugin bundle/ZIP is not a supported stapler container.
The DMG is the stapled offline-verifiable distribution. The plugin is validated
with `codesign`, not application-style `spctl --type execute`, which can reject a
valid non-application bundle.

The final ZIP is extracted and the final DMG mounted read-only. Both shipped
payloads must have valid signatures, universal architecture, exports and package
layout, and byte-identical inventories. Final signed bundle provenance and final
asset checksums are generated **after** signing/notarization/stapling.
`SHA256SUMS` includes the final archives and JSON evidence (excluding itself);
`release-provenance.json` inventories the other assets, excluding itself and
`SHA256SUMS` to avoid circular hashes. Signing credentials are removed even on
failure.

**Windows is unsigned.** No established Authenticode signing mechanism exists in
this repository. Neither Developer ID signing nor notarization signs the PE
payload. The draft notes and provenance explicitly identify this limitation;
do not describe the cross-platform package as Windows-signed.

After all gates pass, the workflow creates a **draft** GitHub release, downloads
its assets again and compares every downloaded byte/checksum. It never makes a
release public. A download/check failure can leave a draft for inspection;
review/delete that draft manually before retrying. Review the draft, evidence
and unsigned-Windows notice before a maintainer separately authorizes public
publication. No workflow should be dispatched merely to test these edits.

## Version preparation

`Bump version` is also manual and read-only. It uploads `version.patch`, without
committing, pushing, tagging or publishing. Download/apply that patch, review
version/resource changes, commit normally, and let CI validate the source before
dispatching a release. Xcode's numeric `CURRENT_PROJECT_VERSION` is independent
of `MARKETING_VERSION`; the existing updater treats the marketing version and
literal Info.plist short version as the release version.

## Download verification

From downloaded release assets, run `shasum -a 256 -c SHA256SUMS`. On macOS:

```
codesign --verify --strict --verbose=2 ULID-X.Y.Z.dmg
xcrun stapler validate ULID-X.Y.Z.dmg
spctl --assess --type open --context context:primary-signature --verbose=2 ULID-X.Y.Z.dmg
```

Mount the image and verify `ULID.bundle` with
`codesign --verify --deep --strict --verbose=2`, then compare its inventory with
`bundle-provenance.json` (whose paths include the `ULID.bundle/` prefix).
These native checks do not replace integration testing in a supported 4D host.

## Optional pinned runtime host acceptance

`Manual pinned 4D host smoke` is separate, manual-only, read-only validation.
It reuses the native build workflow and verifies its same-run artifact before
executing `scripts/host_smoke.py` first interpreted, then with `--compiled`.
The latter requires a structured clean compilation report and a real
compiled-mode smoke success, not merely a runtime process exiting zero.

Select the platform and explicitly provide:

- An HTTPS tool4d **tar.xz** archive URL for a specific runtime version.
- Its independently obtained SHA-256 (64 lowercase hexadecimal characters).
- The executable's forward-slash relative path inside the archive, for example
  `tool4d.app/Contents/MacOS/tool4d` or `tool4d/tool4d.exe`.

No runtime version is automatically resolved or downloaded during ordinary CI.
Archive checksums are verified before safe extraction or execution. Changing
remote archive bytes causes failure, even if the URL remains unchanged. Supply
only a trusted runtime you are licensed/authorized to execute. The workflow
retains source/native/runtime provenance and structured interpreted, compilation
and compiled reports; it does not redistribute the runtime. Scratch projects
stay under `build/host-work`.

Earlier local tool4d 21.1 macOS runs produced zero-exit interpreted and compiled
success reports with no compilation diagnostics. Subsequent runs encountered a
shutdown SIGSEGV (`xbox1150`) reproduced with a minimal no-Plugins baseline;
**repeatable local host acceptance remains blocked**. See README for the current
investigation. The harness must reject a nonzero runtime exit even if a success
JSON exists; its fail-closed behavior is regression-tested on both native CI
platforms. `--baseline` supports a no-Plugins runtime control without bypassing
failure checks.

This optional hosted workflow has not been dispatched as part of these edits,
and **Windows 4D-host acceptance has not been established**. Windows native CTest
coverage is not a substitute for that host check.
