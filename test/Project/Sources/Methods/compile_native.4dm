//%attributes = {}
var $report : Object
var $targets : Collection
$targets:=New collection("x86_64_generic")
If (Is macOS)
	$targets.push("arm64_macOS_lib")
End if
$report:=Compile project(New object("targets"; $targets; "typeInference"; "all"))
File(Folder(fk database folder).path+"ulid-compile.json").setText(JSON Stringify($report))
QUIT 4D
