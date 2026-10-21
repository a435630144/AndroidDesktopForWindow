#!/usr/bin/env bash
# 全量回归：逐个跑 tests/test_*.py，判据只看退出码（别 grep 文案）。
# 用法：bash tools/run_all_tests.sh [日志目录，默认 /tmp/qa_v8]
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="C:/Users/43563/.workbuddy/binaries/python/envs/default/Scripts/python.exe"
LOG="${1:-/tmp/qa_v8}"
mkdir -p "$LOG"
cd "$ROOT" || exit 1

pass=0
fail=0
failed=""
for f in tests/test_*.py; do
  name="$(basename "$f")"
  "$PY" "$f" > "$LOG/$name.log" 2>&1
  rc=$?
  if [ $rc -eq 0 ]; then
    pass=$((pass + 1))
  else
    fail=$((fail + 1))
    failed="$failed $name(rc=$rc)"
    echo "FAIL $name rc=$rc"
  fi
done

smoke="skip"
SMOKE_PATH="smoke_test.py"
[ -f "$SMOKE_PATH" ] || SMOKE_PATH="tests/smoke_test.py"
if [ -f "$SMOKE_PATH" ]; then
  "$PY" "$SMOKE_PATH" > "$LOG/smoke_test.log" 2>&1
  [ $? -eq 0 ] && smoke="ok" || smoke="FAIL"
fi

echo "PASS=$pass FAIL=$fail SMOKE=$smoke"
[ -n "$failed" ] && echo "FAILED:$failed"
exit 0
