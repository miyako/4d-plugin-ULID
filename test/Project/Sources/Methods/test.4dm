//%attributes = {}
$ULID:=Generate ULID("")
$timestamp0:=ULID Get timestamp($ULID)
$timestamp1:=Timestamp:C1445
ASSERT:C1129($timestamp1>=$timestamp0)

$timestamp1:="1970-01-01T00:00:00.001Z"
$ULID:=ULID Set timestamp($ULID; $timestamp1)
$timestamp2:=ULID Get timestamp($ULID)
ASSERT:C1129($timestamp1=$timestamp2)

$UUID:=ULID to UUID("0001C7STHC0G2081040G208104")
//0000587cea2c04040404040404040404
//raw hexadecimal representation, not a UUID field compatibility guarantee

$ULID:=ULID from UUID("0000587cea2c04040404040404040404")
//0001C7STHC0G2081040G208104
//you can exchange this representation with other applications

$ULID:=Generate ULID("")
ASSERT:C1129(Length:C16($ULID)=26)
$UUID:=ULID to UUID($ULID)
ASSERT:C1129(Length:C16($UUID)=32)