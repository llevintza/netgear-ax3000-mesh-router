#!/usr/bin/env bash
# Reproduce the firmware pipeline: download -> verify -> REA region scan -> REA rootfs extraction.
# Usage: tools/fetch-and-extract.sh [MR70|MS70 ...]   (default: both)
# Output: firmware/<M>-V<ver>/ (zip contents), extracted/<M>-regions.json, extracted/<M>-extract.json,
#         extracted/<M>/selected.bin_extract/ (rootfs). All gitignored.
set -euo pipefail

VER=1.0.5.50_2.0.70
BASE=https://www.downloads.netgear.com/files/GDC/MK73S
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
IMAGE=rea-fw
if [ $# -gt 0 ]; then models=("$@"); else models=(MR70 MS70); fi

# Known-good SHA-256 of the official zips (recorded 2026-11-01). bash 3.2-compatible (macOS).
zip_sha() {
  case "$1" in
    MR70) echo 4db0fd7d1154ceeff8e5683ed0685ad6fa23bdfdfe00b46b3a6ac2c11ebe57f4 ;;
    MS70) echo 8c763ae39494032559157a8efaa658d502f0f0edff3753b41ecb8eec0a93cc5d ;;
    *) echo "unknown model: $1" >&2; exit 1 ;;
  esac
}

docker image inspect "$IMAGE" >/dev/null 2>&1 || docker build -t "$IMAGE" "$ROOT/tools"
mkdir -p "$ROOT/firmware" "$ROOT/extracted"

for m in "${models[@]}"; do
  name="$m-V$VER"
  zip="$ROOT/firmware/$name.zip"
  [ -f "$zip" ] || curl -fsSL -o "$zip" "$BASE/$name.zip"
  echo "$(zip_sha "$m")  $zip" | shasum -a 256 -c -
  [ -d "$ROOT/firmware/$name" ] || unzip -q "$zip" -d "$ROOT/firmware/$name"
  chk="/fw/$name/$name.chk"

  # 1. Region scan (binwalk via REA)
  docker run --rm -v "$ROOT/firmware:/fw:ro" "$IMAGE" \
    rea inspect-firmware-regions "$chk" --json > "$ROOT/extracted/$m-regions.json"

  # 2. Locate the SquashFS rootfs from the scan
  read -r off len < <(jq -r '[.. | objects | select(has("offset") and has("size") and ((.description // "") | test("SquashFS")))][0] | "\(.offset) \(.size)"' "$ROOT/extracted/$m-regions.json")
  echo "$m rootfs: offset=$off length=$len"

  # 3. Extract INSIDE the container (bind-mounted output dirs fail on Colima: "Extraction directory
  #    identity changed"), with REA's maximum output budget, then copy out.
  rm -rf "$ROOT/extracted/$m"
  docker run --rm -v "$ROOT/firmware:/fw:ro" -v "$ROOT/extracted:/host" "$IMAGE" sh -c "
    rea extract-firmware '$chk' /work/$m --offset $off --length $len \
      --max-output-bytes 536870912 --max-output-files 20000 \
      --analysis-timeout-ms 600000 --publication-timeout-ms 600000 --json > /host/$m-extract.json
    tar -C /work -cf - $m | tar -C /host -xf -"
  echo "$m: $(find "$ROOT/extracted/$m" -type f | wc -l | tr -d ' ') files in extracted/$m/selected.bin_extract"
done
