![version](https://img.shields.io/badge/version-20%2B-E23089)
![platform](https://img.shields.io/static/v1?label=platform&message=mac-intel%20|%20mac-arm%20|%20win-64&color=blue)
[![license](https://img.shields.io/github/license/miyako/4d-plugin-ULID)](LICENSE)
![downloads](https://img.shields.io/github/downloads/miyako/4d-plugin-ULID/total)

# 4d-plugin-ULID

Generates and converts [ULIDs](https://github.com/ulid/spec) (Universally Unique Lexicographically Sortable Identifiers) — 26-character, sortable, timestamp-prefixed identifiers — and converts between ULID text and the 32-character hexadecimal UUID representation 4D can store in a `UUID` field. All five commands work with plain `Text`; there is no dedicated ULID data type in 4D.

**Platforms:** macOS and Windows. The plugin uses only long-stable, non-version-gated APIs (basic Unicode text conversion, standard C time functions), so no specific minimum OS version is implied.

| Command | Returns | Purpose |
|---|---|---|
| [`Generate ULID`](#generate-ulid) | Text | Create a new ULID from the current time and random entropy |
| [`ULID from UUID`](#ulid-from-uuid) | Text | Convert a 32-character hex UUID to its ULID text form |
| [`ULID to UUID`](#ulid-to-uuid) | Text | Convert a ULID back to its 32-character hex UUID form |
| [`ULID Get timestamp`](#ulid-get-timestamp) | Text | Read the timestamp encoded in a ULID, as ISO 8601 UTC |
| [`ULID Set timestamp`](#ulid-set-timestamp) | Text | Return a copy of a ULID with its timestamp replaced |

---

## Requirements & platform notes

- All parameters are **mandatory Text parameters** — none of the five commands has an optional form.
- A **ULID string must be exactly 26 characters** of valid [Crockford Base32](https://www.crockford.com/base32.html) (digits `0`-`9` and uppercase letters, excluding `I`, `L`, `O`, `U`). A **UUID string must be exactly 32 hexadecimal characters**, no dashes — this is the same 32-character form you'd store in a 4D `UUID` field after stripping its separators.
- **Any command given malformed ULID/UUID text (wrong length, or a character outside the valid alphabet) returns an empty string.** This is the behavior of the fixed source delivered alongside this doc — earlier builds validated less of this input and could behave unpredictably on malformed text. If you're documenting or relying on this against an already-built binary, confirm which version you have.
- `ULID Get timestamp` reads the ULID's timestamp field, which is a 48-bit millisecond count from the Unix epoch (1970-01-01). It cannot represent a date before 1970 or past roughly the year 10889; out-of-range timestamps return an empty string.
- `Generate ULID`'s random entropy comes from a single `std::mt19937` generator shared for the plugin's lifetime — good for uniqueness and lexicographic sort order, not intended as a source of cryptographically unpredictable values.

---

## Generate ULID

### Syntax

```4d
Generate ULID() → Text
```

| Parameter | Type | Description |
|---|---|---|
| Result | Text | A new 26-character ULID |

### Description

Builds a new ULID from the current system time (millisecond precision, UTC) and 80 bits of random entropy. Calling it repeatedly produces lexicographically increasing values as long as system time moves forward, which is the point of the ULID format — you get sortable, roughly-time-ordered unique IDs without a database round-trip.

### Example

From the plugin's own test method (`test.4dm`):
```4d
$ULID:=Generate ULID()
ASSERT:C1129(Length:C16($ULID)=26)
```

Generating several IDs in a loop and confirming they sort in creation order:
```4d
ARRAY TEXT:C222($ids;10)
For:C155($i;1;10)
	$ids{$i}:=Generate ULID()
End for:C155

// $ids is already lexicographically sorted by creation time
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

Converts the 32-character hex form of a UUID (as stored in a 4D `UUID` field, with separators stripped) into the equivalent ULID text. This is a pure re-encoding of the same 128 bits — no timestamp reinterpretation happens, since a plain UUID has no defined timestamp field the way a ULID does.

### Example

From the plugin's own test method (`test.4dm`):
```4d
$ULID:=ULID from UUID("0000587cea2c04040404040404040404")
//0001C7STHC0G2081040G208104
//you can exchange this representation with other applications
```

Round-tripping a UUID field value through ULID text for an external API that expects ULIDs:
```4d
$UUIDField:=UUID:C1487  // or a UUID value read from a table
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

The inverse of [`ULID from UUID`](#ulid-from-uuid): re-encodes a ULID's 128 bits as a 32-character hex string with no dashes, suitable for storing in a 4D `UUID` field.

### Example

From the plugin's own test method (`test.4dm`):
```4d
$UUID:=ULID to UUID("0001C7STHC0G2081040G208104")
//0000587cea2c04040404040404040404
//you can store this representation in a UUID field
```

Converting a freshly generated ULID and confirming the expected length:
```4d
$ULID:=Generate ULID()
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
$ULID:=Generate ULID()
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
	$ids{$i}:=ULID Set timestamp(Generate ULID(); "2020-01-01T00:00:00.000Z")
End for:C155
```

---

## Error handling & troubleshooting

- **Malformed ULID or UUID text returns an empty string, not an error and not a crash.** Always check the result against `""` before using it — none of these commands raises a 4D error on bad input.
- **A `ULID` argument must be exactly 26 characters from the Crockford Base32 alphabet.** Any other length, or any character outside `0-9` / uppercase `A-Z` minus `I`, `L`, `O`, `U`, produces an empty result from `ULID to UUID`, `ULID Get timestamp`, and `ULID Set timestamp`.
- **A `UUID` argument to `ULID from UUID` must be exactly 32 hex characters with no dashes.** Strip any UUID field's formatting before passing it in.
- **An unparsable `timestamp` in `ULID Set timestamp` silently falls back toward the Unix epoch rather than failing.** If the date/time text before any fractional seconds doesn't match `YYYY-MM-DDTHH:MM:SS`, the command encodes a zero timestamp (`1970-01-01T00:00:00.000Z`) with no indication anything was wrong. Validate your timestamp text yourself if this matters to your use case.
- **`ULID Get timestamp` can return an empty string for a syntactically valid but extreme timestamp.** A ULID's timestamp field can encode dates far beyond what your OS can represent as a calendar date; in that case the command returns `""` rather than a garbled date.
- **Don't rely on `Generate ULID`'s randomness for anything security-sensitive.** It's a fast, non-cryptographic generator intended only to make IDs unique, not unpredictable.

---

## Quick reference

```4d
$ULID:=Generate ULID()
$UUID:=ULID to UUID($ULID)
$ULIDBack:=ULID from UUID($UUID)  // == $ULID

$created:=ULID Get timestamp($ULID)
$ULID:=ULID Set timestamp($ULID; "2020-01-01T00:00:00.000Z")

If:C25($ULID="")
	// input was not a well-formed ULID/UUID/timestamp
End if
```
