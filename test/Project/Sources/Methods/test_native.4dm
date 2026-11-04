//%attributes = {}
var $error; $id; $back; $previous : Text
var $bytes : Blob
var $report; $checks : Object
var $ok : Boolean
var $i : Integer
var $milliseconds : Real

$ok:=True
$checks:=New object
$id:=ULID Generate($error)
$checks.generate:=($error="") & (Length($id)=26)
$previous:=$id
For ($i;1;100)
	$id:=ULID Generate($error)
	$ok:=$ok & ($error="") & ($id>$previous)
	$previous:=$id
End for
$checks.monotonic:=$ok
$id:="01ARZ3NDEKTSV4RRFFQ69G5FAV"
$bytes:=ULID To blob($id; $error)
$checks.blobSize:=($error="") & (BLOB size($bytes)=16)
$checks.networkOrder:=($bytes{0}=1) & ($bytes{1}=86) & ($bytes{15}=91)
$back:=ULID From blob($bytes; $error)
$checks.roundtrip:=($error="") & ($back=$id)
For ($i;1;100)
	$bytes:=ULID To blob($id; $error)
	$ok:=$ok & ($error="") & (BLOB size($bytes)=16)
	$back:=ULID From blob($bytes; $error)
	$ok:=$ok & ($error="") & ($back=$id)
End for
$checks.repeated:=$ok
$checks.lowercase:=(ULID Is valid(Lowercase($id))=1)
$checks.overflow:=(ULID Is valid("80000000000000000000000000")=0)
$milliseconds:=ULID Timestamp($id; $error)
$checks.timestamp:=($milliseconds=1469922850259) & ($error="")
SET BLOB SIZE($bytes; 15)
$back:=ULID From blob($bytes; $error)
$checks.invalidBlob:=($back="") & ($error#"")
SET BLOB SIZE($bytes; 17)
$back:=ULID From blob($bytes; $error)
$checks.longBlob:=($back="") & ($error#"")
SET BLOB SIZE($bytes; 0)
$back:=ULID From blob($bytes; $error)
$checks.emptyBlob:=($back="") & ($error#"")
$bytes:=ULID To blob("invalid"; $error)
$checks.invalidText:=(BLOB size($bytes)=0) & ($error#"")
$checks.maximum:=(ULID Timestamp("7ZZZZZZZZZZZZZZZZZZZZZZZZZ"; $error)=281474976710655) & ($error="")
$checks.legacy:=(ULID from UUID("0000587cea2c04040404040404040404")="0001C7STHC0G2081040G208104")
$ok:=$checks.generate & $checks.monotonic & $checks.blobSize & $checks.networkOrder & $checks.roundtrip & $checks.repeated & $checks.lowercase & $checks.overflow & $checks.timestamp & $checks.invalidBlob & $checks.longBlob & $checks.emptyBlob & $checks.invalidText & $checks.maximum & $checks.legacy
$report:=New object("success"; $ok; "checks"; $checks; "milliseconds"; $milliseconds; "runtime"; Application version; "compiled"; Is compiled mode)
File(Folder(fk database folder).path+"ulid-smoke.json").setText(JSON Stringify($report))
QUIT 4D
