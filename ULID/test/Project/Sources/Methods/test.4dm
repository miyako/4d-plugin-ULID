//%attributes = {}
$UUID:=ULID to UUID("0001C7STHC0G2081040G208104")
//0000587cea2c04040404040404040404
//you can store this representation in a UUID field

$ULID:=ULID from UUID("0000587cea2c04040404040404040404")
//0001C7STHC0G2081040G208104
//you can exchange this representation with other applications

$ULID:=Generate ULID()
ASSERT:C1129(Length:C16($ULID)=26)
$UUID:=ULID to UUID($ULID)
ASSERT:C1129(Length:C16($UUID)=32)