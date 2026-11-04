#!/bin/bash
set -euo pipefail

python3 -c 'import os,sys; sys.path.insert(0,"scripts/release"); from preflight import SECRETS; missing=[k for k in (*SECRETS,"RELEASE_TAG","SOURCE_SHA") if not os.environ.get(k)]; assert not missing, "Missing configuration: " + ", ".join(missing)'
[[ "$RELEASE_TAG" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]
[[ "$NOTARYTOOL_TEAM_ID" =~ ^[A-Z0-9]{10}$ ]]
mkdir release-state dist
KEYCHAIN="$PWD/release-state/build.keychain-db"
BUNDLE="$PWD/package/ULID.bundle"
CERT="$PWD/release-state/certificate.p12"
ZIP="$PWD/dist/ULID-${RELEASE_TAG#v}.zip"
DMG="$PWD/dist/ULID-${RELEASE_TAG#v}.dmg"

cleanup() {
  security delete-keychain "$KEYCHAIN" >/dev/null 2>&1 || true
  rm -f "$CERT"
}
trap cleanup EXIT
printf '%s' "$APPLE_DEVELOPER_ID_CERTIFICATE" | base64 --decode > "$CERT"
security create-keychain -p "$KEYCHAIN_PASSWORD" "$KEYCHAIN"
security set-keychain-settings -lut 21600 "$KEYCHAIN"
security unlock-keychain -p "$KEYCHAIN_PASSWORD" "$KEYCHAIN"
security import "$CERT" -P "$APPLE_DEVELOPER_ID_CERTIFICATE_PASSWORD" -t cert -f pkcs12 -k "$KEYCHAIN"
security list-keychains -d user -s "$KEYCHAIN" login.keychain-db
security set-key-partition-list -S apple-tool:,apple:,codesign: -s -k "$KEYCHAIN_PASSWORD" "$KEYCHAIN"
IDENTITY=$(security find-identity -v -p codesigning "$KEYCHAIN" |
  python3 -c 'import os,re,sys; ids=[m.group(1) for m in re.finditer(r"([0-9A-F]{40}) \"Developer ID Application: [^\"]+ \(" + re.escape(os.environ["NOTARYTOOL_TEAM_ID"]) + r"\)\"", sys.stdin.read())]; assert len(ids)==1, "Require exactly one Developer ID Application identity for expected team"; print(ids[0])')
xcrun notarytool store-credentials release-profile --apple-id "$NOTARYTOOL_APPLE_ID" \
  --team-id "$NOTARYTOOL_TEAM_ID" --password "$NOTARYTOOL_PASSWORD" --keychain "$KEYCHAIN"

codesign --force --timestamp --options runtime --keychain "$KEYCHAIN" --sign "$IDENTITY" "$BUNDLE"
codesign --verify --deep --strict --verbose=2 "$BUNDLE"
codesign -d --verbose=4 "$BUNDLE" 2> release-state/bundle-signature.txt
grep -Fx "TeamIdentifier=$NOTARYTOOL_TEAM_ID" release-state/bundle-signature.txt
grep -E '^Authority=Developer ID Application:' release-state/bundle-signature.txt
grep -E '^Timestamp=.' release-state/bundle-signature.txt
grep -E '^CodeDirectory .*flags=.*runtime' release-state/bundle-signature.txt

ditto -c -k --keepParent "$BUNDLE" "$ZIP"
notarize() {
  local artifact="$1" report="$2"
  xcrun notarytool submit "$artifact" --keychain-profile release-profile --keychain "$KEYCHAIN" \
    --wait --output-format json > "$report"
  python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); assert d.get("status")=="Accepted", d' "$report"
}
notarize "$ZIP" release-state/zip-notarization.json
hdiutil create -format UDZO -volname ULID -srcfolder package "$DMG"
codesign --force --timestamp --keychain "$KEYCHAIN" --sign "$IDENTITY" "$DMG"
codesign --verify --strict --verbose=2 "$DMG"
codesign -d --verbose=4 "$DMG" 2> release-state/dmg-signature.txt
grep -Fx "TeamIdentifier=$NOTARYTOOL_TEAM_ID" release-state/dmg-signature.txt
grep -E '^Timestamp=.' release-state/dmg-signature.txt
notarize "$DMG" release-state/dmg-notarization.json
xcrun stapler staple "$DMG"
xcrun stapler validate "$DMG"
codesign --verify --strict --verbose=2 "$DMG"
spctl --assess --type open --context context:primary-signature --verbose=2 "$DMG"

# Re-extract the final ZIP, checking the shipped payload rather than the build path.
mkdir release-state/extracted
ditto -x -k "$ZIP" release-state/extracted
codesign --verify --deep --strict --verbose=2 release-state/extracted/ULID.bundle
mkdir release-state/mounted
hdiutil attach "$DMG" -readonly -nobrowse -mountpoint "$PWD/release-state/mounted"
trap 'hdiutil detach "$PWD/release-state/mounted" >/dev/null 2>&1 || true; cleanup' EXIT
codesign --verify --deep --strict --verbose=2 release-state/mounted/ULID.bundle
python3 -c 'import sys; from pathlib import Path; sys.path.insert(0,"scripts/release"); from artifacts import inventory,validate; a=Path("release-state/extracted/ULID.bundle"); b=Path("release-state/mounted/ULID.bundle"); validate(a,["macos","windows"]); validate(b,["macos","windows"]); assert inventory(a)==inventory(b), "ZIP and DMG payloads differ"'
hdiutil detach "$PWD/release-state/mounted"
trap cleanup EXIT
python3 scripts/release/artifacts.py inventory release-state/extracted dist/bundle-provenance.json --sha "$SOURCE_SHA"
cp inputs/macos/provenance.json dist/macos-pre-signing-provenance.json
cp inputs/windows/provenance.json dist/windows-unsigned-provenance.json
cp release-state/*-notarization.json dist/
# Hash only after signing, notarization and stapling have finished changing bytes.
python3 scripts/release/artifacts.py inventory dist release-state/final-assets.json --sha "$SOURCE_SHA"
cp release-state/final-assets.json dist/release-provenance.json
(cd dist && shasum -a 256 ./* > SHA256SUMS)
