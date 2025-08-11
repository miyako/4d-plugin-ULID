![version](https://img.shields.io/badge/version-20%2B-E23089)
![platform](https://img.shields.io/static/v1?label=platform&message=mac-intel%20|%20mac-arm%20|%20win-64&color=blue)
[![license](https://img.shields.io/github/license/miyako/4d-plugin-ULID)](LICENSE)
![downloads](https://img.shields.io/github/downloads/miyako/4d-plugin-ULID/total)

# 4d-plugin-ULID
ULID↔UUID converter 

based on [suyash/ulid](https://github.com/suyash/ulid)

## usage

```4d
$UUID:=ULID to UUID("0001C7STHC0G2081040G208104")
//0000587cea2c04040404040404040404
//you can store this representation in a UUID field

$ULID:=ULID from UUID("0000587cea2c04040404040404040404")
//0001C7STHC0G2081040G208104
//you can exchange this representation with other applications

$ULID:=Generate ULID()
ASSERT(Length($ULID)=26)
$UUID:=ULID to UUID($ULID)
ASSERT(Length($UUID)=32)
```

## timestamp

```4d
$ULID:=Generate ULID()
$timestamp0:=ULID Get timestamp($ULID)
$timestamp1:=Timestamp
ASSERT($timestamp1>=$timestamp0)

$timestamp1:="1970-01-01T00:00:00.001Z"
$ULID:=ULID Set timestamp($ULID; $timestamp1)
$timestamp2:=ULID Get timestamp($ULID)
ASSERT($timestamp1=$timestamp2)
```
