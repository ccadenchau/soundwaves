#!/usr/bin/env bash
# One command to check everything.   ./check.sh            unit tests + browser tests + the end-to-end cases
#                                    ./check.sh --quick     unit tests only (10 seconds)
set -uo pipefail
cd "$(dirname "$0")"
QUICK=0; [ "${1:-}" = "--quick" ] && QUICK=1
[ -x .venv/bin/python ] || { echo "Run ./run.sh (or ./run.sh --fast) once first to set up."; exit 1; }
PY=.venv/bin/python
fail=0
quiet() { grep -v -i -E "warning|re\.match|return fn|check_backward" || true; }

echo "==> Python unit tests"
$PY -m unittest pianocoach.test_audio_cleaner pianocoach.test_clean pianocoach.test_scoreprep pianocoach.test_report pianocoach.test_partial \
  pianocoach.test_pipeline pianocoach.test_live pianocoach.test_transkun sheet_downloader.test_reference \
  testing.alignment.test_notation 2>&1 | quiet | tail -4 | tee /tmp/pianocoach-unit.txt
grep -q "^OK" /tmp/pianocoach-unit.txt || fail=1

if [ -s "$HOME/.nvm/nvm.sh" ]; then . "$HOME/.nvm/nvm.sh" >/dev/null 2>&1; fi
if command -v node >/dev/null 2>&1; then
  echo; echo "==> Browser logic tests (node)"
  node --test --test-reporter=tap pianocoach-ui/*.test.cjs 2>&1 | grep -E "^# (tests|pass|fail)" || fail=1
  node --test pianocoach-ui/*.test.cjs >/dev/null 2>&1 || fail=1
else
  echo; echo "==> Browser logic tests skipped (node not installed)"
fi

if [ "$QUICK" = 0 ]; then
  echo; echo "==> End-to-end cases (planted mistakes -> converters -> findings)"
  $PY -m pianocoach.selftest 2>&1 | quiet || true
  $PY -m pianocoach.selftest >/dev/null 2>&1 || fail=1
fi

echo
if [ "$fail" = 0 ]; then echo "ALL CHECKS PASSED"; else echo "SOMETHING FAILED, see above"; fi
exit $fail
