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
MOUNTED=false

bounded() {
  local label="$1"
  shift
  python3 scripts/release/bounded.py --label "$label" --timeout 120 -- "$@"
}
sign_code() {
  local label="$1"
  shift
  python3 scripts/release/bounded.py --label "$label" --timeout 180 -- "$@"
}
cleanup() {
  local status=$?
  if "$MOUNTED"; then
    bounded "Detach DMG during cleanup" hdiutil detach "$PWD/release-state/mounted" || status=1
  fi
  if [ -f "$KEYCHAIN" ]; then
    bounded "Delete signing keychain" security delete-keychain "$KEYCHAIN" || status=1
  fi
  rm -f "$CERT" || status=1
  if [ "$status" -ne 0 ]; then
    echo "ERROR: signing/validation or credential cleanup failed; publication blocked" >&2
  fi
  exit "$status"
}
trap cleanup EXIT
printf '%s' "$APPLE_DEVELOPER_ID_CERTIFICATE" | base64 --decode > "$CERT"
bounded "Create signing keychain" security create-keychain -p "$KEYCHAIN_PASSWORD" "$KEYCHAIN"
bounded "Configure signing keychain" security set-keychain-settings -lut 21600 "$KEYCHAIN"
bounded "Unlock signing keychain" security unlock-keychain -p "$KEYCHAIN_PASSWORD" "$KEYCHAIN"
bounded "Import signing identity" security import "$CERT" -P "$APPLE_DEVELOPER_ID_CERTIFICATE_PASSWORD" \
  -t cert -f pkcs12 -k "$KEYCHAIN" -T /usr/bin/codesign
bounded "Set keychain search list" security list-keychains -d user -s "$KEYCHAIN" login.keychain-db
bounded "Authorize signing key access" security set-key-partition-list -S apple-tool:,apple:,codesign: -s -k "$KEYCHAIN_PASSWORD" "$KEYCHAIN"
python3 scripts/release/bounded.py --label "Find signing identity" --timeout 120 \
  --output release-state/identity.txt -- security find-identity -v -p codesigning "$KEYCHAIN"
IDENTITY=$(python3 -c 'import os,re,sys; ids=[m.group(1) for m in re.finditer(r"([0-9A-F]{40}) \"Developer ID Application: [^\"]+ \(" + re.escape(os.environ["NOTARYTOOL_TEAM_ID"]) + r"\)\"", sys.stdin.read())]; assert len(ids)==1, "Require exactly one Developer ID Application identity for expected team"; print(ids[0])' < release-state/identity.txt)
bounded "Validate and store notarization credentials" xcrun notarytool store-credentials release-profile --apple-id "$NOTARYTOOL_APPLE_ID" \
  --team-id "$NOTARYTOOL_TEAM_ID" --password "$NOTARYTOOL_PASSWORD" --keychain "$KEYCHAIN"

sign_code "Sign bundle with secure timestamp" codesign --force --timestamp --options runtime --keychain "$KEYCHAIN" --sign "$IDENTITY" "$BUNDLE"
bounded "Verify bundle signature" codesign --verify --deep --strict --verbose=2 "$BUNDLE"
bounded "Inspect bundle signature" codesign -d --verbose=4 "$BUNDLE" 2> release-state/bundle-signature.txt
grep -Fx "TeamIdentifier=$NOTARYTOOL_TEAM_ID" release-state/bundle-signature.txt
grep -E '^Authority=Developer ID Application:' release-state/bundle-signature.txt
grep -E '^Timestamp=.' release-state/bundle-signature.txt
grep -E '^CodeDirectory .*flags=.*runtime' release-state/bundle-signature.txt

bounded "Create signed ZIP" ditto -c -k --keepParent "$BUNDLE" "$ZIP"
notarize() {
  local artifact="$1" report="$2"
  python3 scripts/release/notarize.py "$artifact" "$report" "$KEYCHAIN"
}
notarize "$ZIP" release-state/zip-notarization.json
bounded "Create DMG" hdiutil create -format UDZO -volname ULID -srcfolder package "$DMG"
sign_code "Sign DMG with secure timestamp" codesign --force --timestamp --keychain "$KEYCHAIN" --sign "$IDENTITY" "$DMG"
bounded "Verify DMG signature" codesign --verify --strict --verbose=2 "$DMG"
bounded "Inspect DMG signature" codesign -d --verbose=4 "$DMG" 2> release-state/dmg-signature.txt
grep -Fx "TeamIdentifier=$NOTARYTOOL_TEAM_ID" release-state/dmg-signature.txt
grep -E '^Timestamp=.' release-state/dmg-signature.txt
notarize "$DMG" release-state/dmg-notarization.json
bounded "Staple DMG ticket" xcrun stapler staple "$DMG"
bounded "Validate DMG ticket" xcrun stapler validate "$DMG"
bounded "Verify final DMG signature" codesign --verify --strict --verbose=2 "$DMG"
bounded "Assess DMG Gatekeeper policy" spctl --assess --type open --context context:primary-signature --verbose=2 "$DMG"

# Re-extract the final ZIP, checking the shipped payload rather than the build path.
mkdir release-state/extracted
bounded "Extract final ZIP" ditto -x -k "$ZIP" release-state/extracted
bounded "Verify shipped ZIP payload" codesign --verify --deep --strict --verbose=2 release-state/extracted/ULID.bundle
mkdir release-state/mounted
MOUNTED=true
bounded "Mount final DMG" hdiutil attach "$DMG" -readonly -nobrowse -mountpoint "$PWD/release-state/mounted"
bounded "Verify shipped DMG payload" codesign --verify --deep --strict --verbose=2 release-state/mounted/ULID.bundle
python3 -c 'import sys; from pathlib import Path; sys.path.insert(0,"scripts/release"); from artifacts import inventory,validate; a=Path("release-state/extracted/ULID.bundle"); b=Path("release-state/mounted/ULID.bundle"); validate(a,["macos","windows"]); validate(b,["macos","windows"]); assert inventory(a)==inventory(b), "ZIP and DMG payloads differ"'
bounded "Detach final DMG" hdiutil detach "$PWD/release-state/mounted"
MOUNTED=false
python3 scripts/release/artifacts.py inventory release-state/extracted dist/bundle-provenance.json --sha "$SOURCE_SHA"
cp inputs/macos/provenance.json dist/macos-pre-signing-provenance.json
cp inputs/windows/provenance.json dist/windows-unsigned-provenance.json
cp release-state/*-notarization.json dist/
# Hash only after signing, notarization and stapling have finished changing bytes.
python3 scripts/release/artifacts.py inventory dist release-state/final-assets.json --sha "$SOURCE_SHA"
cp release-state/final-assets.json dist/release-provenance.json
(cd dist && shasum -a 256 ./* > SHA256SUMS)
