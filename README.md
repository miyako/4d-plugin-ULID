![version](https://img.shields.io/badge/version-20%2B-E23089)
![platform](https://img.shields.io/static/v1?label=platform&message=mac-intel%20|%20mac-arm%20|%20win-64&color=blue)
[![license](https://img.shields.io/github/license/miyako/4d-plugin-ULID)](LICENSE)
![downloads](https://img.shields.io/github/downloads/miyako/4d-plugin-ULID/total)

# 4d-plugin-ULID

Generates and converts [ULIDs](https://github.com/ulid/spec): 26-character identifiers containing a 48-bit Unix millisecond timestamp and 80-bit suffix. The original five command IDs and implementations are retained; only the legacy generator's public name is now `_o_Generate ULID` to mark it obsolete. Five additional commands provide strict validation, OS-secure monotonic generation, exact numeric timestamps, and functional **classic BLOB** conversion.

**Build targets:** macOS universal (Intel + Apple Silicon, deployment target 11.5) and Windows x64. No Linux, Windows ARM64 or 32-bit distribution is built. See [release and secret setup](RELEASE.md).

## Install and quickstart

Copy the complete `ULID.bundle` from a reviewed release archive into the application's `Plugins` folder and restart 4D. Do not mix individual executable/resource files from different versions. The committed historical ZIP, DMG and `test/Plugins` bundle are **not** rebuilt by these source changes.

Store canonical ULIDs in an ordinary **indexed Text field**. A ULID is not a UUID, and no compatibility with 4D's UUID field semantics is promised. The legacy commands containing “UUID” in their names are simply raw 128-bit hexadecimal re-encodings.

```4d
var $id; $back; $error : Text
var $bytes : Blob  // classic BLOB, NOT a boxed 4D.Blob object
var $milliseconds : Real

$id:=ULID Generate($error)
If ($error="")
    $bytes:=ULID To blob($id; $error)
    If ($error="")
        $back:=ULID From blob($bytes; $error)
    End if
End if
If ($error#"")
    // Handle the error before using any result.
    ALERT($error)
End if
$milliseconds:=ULID Timestamp($id; $error)
```

### Strict API (new command IDs 6–10)

| Command | Result | Error parameter |
|---|---|---|
| `ULID Generate($error)` | Text: secure monotonic ULID | Text output |
| `ULID To blob($id; $error)` | Classic BLOB: 16 network-order bytes | Text output |
| `ULID From blob($bytes; $error)` | Text: canonical uppercase ULID | Text output |
| `ULID Timestamp($id; $error)` | Real: exact Unix milliseconds | Text output |
| `ULID Is valid($id)` | Longint: 1 valid, 0 invalid | None; a validation predicate |

Pass a writable Text variable for **every** `$error` argument. It is cleared on success and set to a descriptive message on failure. Failed conversions/generation return empty Text/BLOB; failed timestamp extraction returns `-1`, never the valid epoch value `0`. Check `$error` immediately. These commands do not raise a 4D language error; the bundled SDK only exposes the last SDK error, not a plug-in exception-raising API. Explicit per-call output avoids shared last-error state across cooperative/preemptive processes. The legacy silent-input behavior below is retained only for compatibility.

Strict text decoding accepts ASCII uppercase/lowercase, exactly 26 characters, and rejects `I`, `L`, `O`, `U`, embedded NUL, non-ASCII and a first digit greater than `7` (128-bit overflow). Output is always uppercase. Timestamp `281474976710655` is accepted: all 48-bit millisecond integers are exactly representable by a 4D Real/double; **do not use Longint**.

Binary conversion is a functional return, not a BLOB output argument. From-blob requires **exactly 16 bytes**, including leading zeros, ordered most-significant byte first: six timestamp bytes then ten suffix bytes. Every 16-byte sequence has a ULID encoding. The SDK manifest tokens are `ULID To blob(&T;&T):O` and `ULID From blob(&O;&T):T`; `PA_ReturnBlob` supplies the result and the host copies/owns it. The timestamp return token is `:8` for `PA_ReturnDouble`. These are ABI requirements: `X`/`&X` and `:R` do not implement these SDK contracts. See the [4D classic BLOB documentation](https://developer.4d.com/docs/19/Concepts/blob).

### Ordering and randomness

`ULID Generate` uses macOS `getentropy` / Windows `BCryptGenRandom` for ten fresh random bytes when uninitialized or the clock advances. Within the same millisecond or after clock rollback, a mutex-protected **process-wide** generator retains its timestamp and increments the 80-bit suffix. Overflow and OS RNG failure are explicit errors; failed calls do not commit generator state. It does not busy-wait for the clock.

Ordering is allocation order within one running 4D process, **not** response/transaction commit order, cross-host order, or order across restarts. IDs are probabilistically unique, reveal time, and are not secrets or authentication tokens. The strict generator is separate from obsolete `_o_Generate ULID`, whose implementation and behavior are retained. Batch/collection commands are not provided.

### Build and verification

```sh
# On macOS; omit the architecture option for Windows x64.
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release '-DCMAKE_OSX_ARCHITECTURES=arm64;x86_64'
cmake --build build --config Release
ctest --test-dir build -C Release --output-on-failure
# Fresh bundle: build/package/ULID.bundle
python3 scripts/host_smoke.py --runtime "/path/to/tool4d"
python3 scripts/host_smoke.py --runtime "/path/to/tool4d" --compiled --report build/host-compiled-report.json
```

Native tests cover pinned spec vectors, strict decoding, exact bytes, injected clock/RNG failure, rollback, overflow, concurrency and mock SDK dispatch. The mock tests alone are **not** 4D runtime acceptance. The host runner isolates the project and freshly built plug-in, rejects missing/false reports, and in compiled mode requires `Compile project` success with no diagnostics and `compiled: true` in the runtime report.

Locally exercised: macOS 26.7, Xcode 26.6 universal CMake and existing Xcode project builds, arm64 tool4d 21.1 (`21.100468`). Initial source and compiled runs exited zero with all reported checks true and no compile diagnostics: 100 repeated classic-BLOB roundtrips, network-order bytes, invalid inputs/errors, timestamp precision and legacy conversion. The renamed build also passed source and compiled smoke runs with zero process exits, no compile diagnostics, and both `obsoleteGenerator` and `oldNameToken` checks true.

**Known host repeatability limitation:** earlier subsequent runs produced `xbox 1150` and a shutdown SIGSEGV, also reproduced in a minimal project with **no Plugins directory**. The later successful renamed-build runs do not diagnose or prove resolution of that shutdown issue. The runner still rejects nonzero exits even if a success report was written.

Reproduce the no-plug-in control with `python3 scripts/host_smoke.py --runtime "/path/to/tool4d" --baseline --report build/baseline-report.json`. Failure diagnostics, command and exit code are retained beside the report under a unique `host-failure-*` directory. Stale reports are removed before each run. Intel runtime execution, Windows builds/runtime, minimum macOS 11.5 runtime, and 4D preemptive-process execution are not established by the local run. The native generator is synchronized and the manifest permits preemptive calls; that declaration is not a preemptive-host test.

Vendored source/SDK files remain in-tree, without dependency updates or generated binaries. Immutable reference revisions and licenses are in [THIRD_PARTY.md](THIRD_PARTY.md).

## Legacy text API (command IDs 1–5)

### Generator rename and compatibility

Only the old generator is marked obsolete: `Generate ULID` is now
`_o_Generate ULID`, still command **ID 3** with the same ignored Text argument,
Text result, implementation and behavior. `_o_` identifies its nonsecure,
nonmonotonic generation as obsolete; use **`ULID Generate($error)`** for new
code and handle its error output. The distinct `ULID from UUID`, `ULID to UUID`,
`ULID Get timestamp` and `ULID Set timestamp` commands are **not** marked
obsolete or renamed.

The plug-in ID remains `20000` and all command ordinals remain unchanged.
[4D token references](https://doc.4d.com/4Dv20/4D/20.6/Using-tokens-in-formulas.300-7487422.en.html)
identify plug-in commands by `:P<pluginID>:<commandIndex>`; retaining
`:P20000:3` preserves selector resolution for those references, including an
old-spelling explicit token such as `Generate ULID:P20000:3("")`.
This is **not universal textual-source compatibility**: plain untokenized
`Generate ULID("")` calls, pasted/exported source and dynamic formula strings
may require the new `_o_Generate ULID("")` spelling or an explicit token.
No old-name alias is registered. Recompile and test existing projects with the
new bundle; do not infer acceptance of this renamed build from tests of an older
binary.

On the tested 4D 21.1 host, the renamed plain command and old-spelling explicit
token above passed both interpreted and compiled smoke execution. A separate
negative `Compile project` check of untokenized `Generate ULID("")` failed
with “The variable Generate ULID is not a method.” That plain source must be
updated on this host; other host versions and existing project formats still
require migration testing.

| Command | Returns | Purpose |
|---|---|---|
| [`_o_Generate ULID`](#obsolete-generator) | Text | Obsolete nonsecure, nonmonotonic generation; prefer `ULID Generate($error)` |
| [`ULID from UUID`](#ulid-from-uuid) | Text | Convert a 32-character hex UUID to its ULID text form |
| [`ULID to UUID`](#ulid-to-uuid) | Text | Convert a ULID back to its 32-character hex UUID form |
| [`ULID Get timestamp`](#ulid-get-timestamp) | Text | Read the timestamp encoded in a ULID, as ISO 8601 UTC |
| [`ULID Set timestamp`](#ulid-set-timestamp) | Text | Return a copy of a ULID with its timestamp replaced |

---

## Requirements & platform notes

- Legacy parameters are Text. The manifest retains an ignored Text argument for `_o_Generate ULID`; use `_o_Generate ULID("")` for diagnostic-free compilation. Calls omitting it continue to work interpreted.
- Legacy ULID input must be exactly 26 uppercase Crockford Base32 characters. Legacy validation does not reject leading-digit overflow; use the strict API for untrusted input. The legacy “UUID” input is exactly 32 hexadecimal characters, no dashes.
- **Any command given malformed ULID/UUID text (wrong length, or a character outside the valid alphabet) returns an empty string.** This is the behavior of the fixed source delivered alongside this doc — earlier builds validated less of this input and could behave unpredictably on malformed text. If you're documenting or relying on this against an already-built binary, confirm which version you have.
- `ULID Get timestamp` reads the ULID's timestamp field, which is a 48-bit millisecond count from the Unix epoch (1970-01-01). It cannot represent a date before 1970 or past roughly the year 10889; out-of-range timestamps return an empty string.
- `_o_Generate ULID`'s entropy comes from a single shared `std::mt19937` generator. It is not cryptographically unpredictable or monotonic.

---

## Obsolete generator

### Syntax

```4d
_o_Generate ULID(ignoredText) → Text
```

| Parameter | Type | Description |
|---|---|---|
| Result | Text | A new 26-character ULID |

### Description

Builds a ULID from system time and non-cryptographic `mt19937` entropy. Same-millisecond calls are not sorted; clock rollback can move timestamps backward. Use `ULID Generate` for monotonic semantics.

### Example

From the plugin's own test method (`test.4dm`):
```4d
$ULID:=_o_Generate ULID("")
ASSERT:C1129(Length:C16($ULID)=26)
```

Generating several IDs (sort explicitly if needed):
```4d
ARRAY TEXT:C222($ids;10)
For:C155($i;1;10)
	$ids{$i}:=_o_Generate ULID("")
End for:C155

// Same-millisecond legacy IDs are not necessarily sorted.
```

---

## ULID from UUID

### Syntax

```4d
ULID from UUID(UUID) → Text
```

| Parameter | Type | Description |
|---|---|---|
| `UUID` | Text | A 32-character hexadecimal UUID, no dashes |
| Result | Text | The equivalent 26-character ULID, or an empty string if `UUID` isn't exactly 32 hex characters |

### Description

Re-encodes 32 hexadecimal characters as ULID text. This does not establish UUID version/variant or 4D UUID-field compatibility.

### Example

From the plugin's own test method (`test.4dm`):
```4d
$ULID:=ULID from UUID("0000587cea2c04040404040404040404")
//0001C7STHC0G2081040G208104
//you can exchange this representation with other applications
```

Re-encoding an existing hexadecimal identifier:
```4d
$UUIDField:=UUID:C1487
$ULIDText:=ULID from UUID($UUIDField)
If:C25($ULIDText#"")
	// send $ULIDText to the external system
End if
```

---

## ULID to UUID

### Syntax

```4d
ULID to UUID(ULID) → Text
```

| Parameter | Type | Description |
|---|---|---|
| `ULID` | Text | A 26-character ULID |
| Result | Text | The equivalent 32-character hexadecimal UUID, or an empty string if `ULID` isn't a well-formed 26-character ULID |

### Description

The inverse of [`ULID from UUID`](#ulid-from-uuid): re-encodes the bits as 32 lowercase hexadecimal characters without UUID semantic guarantees.

### Example

From the plugin's own test method (`test.4dm`):
```4d
$UUID:=ULID to UUID("0001C7STHC0G2081040G208104")
//0000587cea2c04040404040404040404
//raw hexadecimal representation
```

Converting a freshly generated ULID and confirming the expected length:
```4d
$ULID:=_o_Generate ULID("")
ASSERT:C1129(Length:C16($ULID)=26)
$UUID:=ULID to UUID($ULID)
ASSERT:C1129(Length:C16($UUID)=32)
```

---

## ULID Get timestamp

### Syntax

```4d
ULID Get timestamp(ULID) → Text
```

| Parameter | Type | Description |
|---|---|---|
| `ULID` | Text | A 26-character ULID |
| Result | Text | The ULID's embedded creation time, as an ISO 8601 UTC string with millisecond precision (e.g. `1970-01-01T00:00:00.001Z`), or an empty string if `ULID` isn't a well-formed ULID or its timestamp is out of range |

### Description

Reads the first 48 bits of the ULID — its timestamp field — and formats it as `YYYY-MM-DDTHH:MM:SS.sssZ` in UTC. The format always includes exactly three millisecond digits and a trailing `Z`.

### Example

From the plugin's own test method (`test.4dm`), comparing a freshly generated ULID's timestamp against the current time:
```4d
$ULID:=_o_Generate ULID("")
$timestamp0:=ULID Get timestamp($ULID)
$timestamp1:=Timestamp:C1445
ASSERT:C1129($timestamp1>=$timestamp0)
```

Extracting and displaying a ULID's creation date:
```4d
$ULID:="01ARZ3NDEKTSV4RRFFQ69G5FAV"
$created:=ULID Get timestamp($ULID)
If:C25($created#"")
	ALERT:C41("Created at: "+$created)
End if
```

---

## ULID Set timestamp

### Syntax

```4d
ULID Set timestamp(ULID; timestamp) → Text
```

| Parameter | Type | Description |
|---|---|---|
| `ULID` | Text | A 26-character ULID whose timestamp field will be replaced |
| `timestamp` | Text | An ISO 8601 UTC string, e.g. `1970-01-01T00:00:00.001Z` |
| Result | Text | A new 26-character ULID with `timestamp` encoded into its timestamp field and the original ULID's entropy (random tail) unchanged, or an empty string if `ULID` isn't well-formed |

### Description

Replaces only the timestamp portion of `ULID`; the 80 bits of entropy from the original ULID carry over unmodified into the result. `timestamp` is expected in the `YYYY-MM-DDTHH:MM:SS` form, optionally followed by `.sss` milliseconds and a trailing `Z`; see the timestamp-parsing caveat below for what happens with text that doesn't match this shape.

### Example

From the plugin's own test method (`test.4dm`):
```4d
$timestamp1:="1970-01-01T00:00:00.001Z"
$ULID:=ULID Set timestamp($ULID; $timestamp1)
$timestamp2:=ULID Get timestamp($ULID)
ASSERT:C1129($timestamp1=$timestamp2)
```

Backdating a batch of ULIDs to a fixed timestamp while keeping each one's own randomness distinct:
```4d
ARRAY TEXT:C222($ids;5)
For:C155($i;1;5)
	$ids{$i}:=ULID Set timestamp(_o_Generate ULID(""); "2020-01-01T00:00:00.000Z")
End for:C155
```

---

## Error handling & troubleshooting

- **Malformed ULID or UUID text returns an empty string, not an error and not a crash.** Always check the result against `""` before using it — none of these commands raises a 4D error on bad input.
- **A `ULID` argument must be exactly 26 characters from the Crockford Base32 alphabet.** Any other length, or any character outside `0-9` / uppercase `A-Z` minus `I`, `L`, `O`, `U`, produces an empty result from `ULID to UUID`, `ULID Get timestamp`, and `ULID Set timestamp`.
- **A `UUID` argument to `ULID from UUID` must be exactly 32 hex characters with no dashes.** Strip any UUID field's formatting before passing it in.
- **An unparsable `timestamp` in `ULID Set timestamp` silently falls back toward the Unix epoch rather than failing.** If the date/time text before any fractional seconds doesn't match `YYYY-MM-DDTHH:MM:SS`, the command encodes a zero timestamp (`1970-01-01T00:00:00.000Z`) with no indication anything was wrong. Validate your timestamp text yourself if this matters to your use case.
- **`ULID Get timestamp` can return an empty string for a syntactically valid but extreme timestamp.** A ULID's timestamp field can encode dates far beyond what your OS can represent as a calendar date; in that case the command returns `""` rather than a garbled date.
- **Don't rely on `_o_Generate ULID`'s randomness for anything security-sensitive.** It is obsolete, non-cryptographic generation; use `ULID Generate($error)` instead, and never treat ULIDs as secrets.

---

## Quick reference

```4d
$ULID:=_o_Generate ULID("")
$UUID:=ULID to UUID($ULID)
$ULIDBack:=ULID from UUID($UUID)  // == $ULID

$created:=ULID Get timestamp($ULID)
$ULID:=ULID Set timestamp($ULID; "2020-01-01T00:00:00.000Z")

If:C25($ULID="")
	// input was not a well-formed ULID/UUID/timestamp
End if
```
