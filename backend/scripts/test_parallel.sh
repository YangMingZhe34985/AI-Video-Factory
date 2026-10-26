#!/bin/bash
# Full backend regression in parallel groups (D-063). Run from any checkout:
#   bash backend/scripts/test_parallel.sh [groups]
# Each group gets its own pytest basetemp; tests already isolate SQLite/storage.
set -u
GROUPS_N=${1:-12}
BACKEND="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON=${PYTHON:-/c/Users/MingZheYang/anaconda3/envs/video-factory/python.exe}
FFMPEG_DEFAULT="$(cd "$BACKEND/.." && pwd)/.venv/Lib/site-packages/imageio_ffmpeg/binaries/ffmpeg-win-x86_64-v7.1.exe"
export FFMPEG_BINARY=${FFMPEG_BINARY:-$FFMPEG_DEFAULT}
OUT="${TMPDIR:-${TEMP:-/tmp}}/cc-parallel-$(date +%m%d%H%M%S)"
mkdir -p "$OUT"
cd "$BACKEND"
ls tests/test_*.py | sort > "$OUT/files.txt"
for g in $(seq 0 $((GROUPS_N - 1))); do
  awk -v g="$g" -v n="$GROUPS_N" 'NR % n == g' "$OUT/files.txt" > "$OUT/group$g.txt"
  ( "$PYTHON" -m pytest -q -p no:cacheprovider --basetemp="$OUT/t$g" $(cat "$OUT/group$g.txt") \
      > "$OUT/group$g.log" 2>&1; echo "exit=$?" >> "$OUT/group$g.log" ) &
done
wait
status=0
for g in $(seq 0 $((GROUPS_N - 1))); do
  summary=$(grep -E '(passed|failed|error)' "$OUT/group$g.log" | tail -1)
  echo "group$g: $summary"
  grep -q '^exit=0$' "$OUT/group$g.log" || status=1
done
grep -h '^FAILED\|^ERROR' "$OUT"/group*.log
echo "logs: $OUT"
exit $status
