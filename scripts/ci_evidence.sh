#!/usr/bin/env bash
# fleet/tests: lint, format, type and test checks for the commit that is checked out.
#
# Prints exactly one annotation titled "fleet-verdict" and exits 0 only on PASS:
#   ::notice title=fleet-verdict::PASS <summary>
#   ::error title=fleet-verdict::FAIL <reason>      lint, format, type or test failures
#   ::error title=fleet-verdict::UNKNOWN <reason>   could not tell: no tests collected,
#                                                   a tool crashed or was misused, timeout
# Tool output is printed with workflow commands disabled, so nothing it prints can
# pose as a verdict.
#
# Environment:
#   FLEET_VENV          virtualenv holding the dev tools (default: .venv, see `make setup`)
#   FLEET_STEP_TIMEOUT  seconds allowed per step (default: 300)
set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

BIN="${FLEET_VENV:-.venv}/bin"
STEP_TIMEOUT="${FLEET_STEP_TIMEOUT:-300}"
SHA="$(git rev-parse --short=12 HEAD 2>/dev/null || echo unknown)"
TOKEN="fleet-$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n')"
LOGS="$(mktemp -d)"

failures=()
unknowns=()
verdict_sent=0

escape() {
  local s="$1"
  s="${s//'%'/'%25'}"
  s="${s//$'\r'/'%0D'}"
  s="${s//$'\n'/'%0A'}"
  printf '%s' "$s"
}

verdict() {
  local kind="$1" message="$2" level=error
  [[ "$kind" == PASS ]] && level=notice
  printf '::%s title=fleet-verdict::%s %s\n' "$level" "$kind" "$(escape "$message")"
  if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
    printf '### fleet/tests: %s\n\n%s\n' "$kind" "$message" >>"$GITHUB_STEP_SUMMARY"
  fi
  verdict_sent=1
}

finish() {
  local code=$?
  rm -rf "$LOGS"
  if ((!verdict_sent)); then
    verdict UNKNOWN "ci_evidence.sh stopped before reaching a verdict (exit $code) at $SHA"
    exit 1
  fi
  exit "$code"
}
trap finish EXIT

join() {
  local sep="$1" out="$2"
  shift 2
  for item in "$@"; do out+="$sep$item"; done
  printf '%s' "$out"
}

# step <log-name> <title> <command...>: run with a timeout and capture the output.
step() {
  local log="$LOGS/$1.log" title="$2"
  shift 2
  echo "::group::$title"
  echo "::stop-commands::$TOKEN"
  timeout --kill-after=15 "$STEP_TIMEOUT" "$@" 2>&1 | tee "$log"
  local code=${PIPESTATUS[0]}
  echo "::$TOKEN::"
  echo "::endgroup::"
  return "$code"
}

# classify <title> <exit code>: exit 1 means the check found problems.
classify() {
  local title="$1" code="$2"
  case "$code" in
    0) ;;
    1) failures+=("$title reported problems") ;;
    124 | 137) unknowns+=("$title timed out after ${STEP_TIMEOUT}s") ;;
    *) unknowns+=("$title exited $code") ;;
  esac
}

pytest_summary() {
  grep -E '[0-9]+ (passed|failed|errors?|skipped|xfailed|xpassed|deselected)|no tests ran' "$1" \
    | tail -n 1 | sed -E 's/^=+ //; s/ =+$//'
}

for tool in ruff mypy pytest; do
  if [[ ! -x "$BIN/$tool" ]]; then
    verdict UNKNOWN "$BIN/$tool is missing (did 'make setup' succeed?) at $SHA"
    exit 1
  fi
done

step ruff "ruff check" "$BIN/ruff" check .
classify "ruff check" $?

step format "ruff format --check" "$BIN/ruff" format --check .
classify "ruff format --check" $?

step mypy "mypy app" "$BIN/mypy" app
classify "mypy" $?

step pytest "pytest" "$BIN/pytest" -q
code=$?
tests="$(pytest_summary "$LOGS/pytest.log")"
case "$code" in
  0) ;;
  1)
    if grep -qE '^E? *Failed: Timeout >|\+{5} Timeout \+{5}' "$LOGS/pytest.log"; then
      unknowns+=("pytest-timeout stopped a test ($tests)")
    else
      failures+=("pytest: ${tests:-tests failed}")
    fi
    ;;
  2) unknowns+=("pytest was interrupted, e.g. by a collection error (${tests:-exit 2})") ;;
  3) unknowns+=("pytest hit an internal error") ;;
  4) unknowns+=("pytest usage error") ;;
  5) unknowns+=("pytest collected no tests") ;;
  124 | 137) unknowns+=("pytest timed out after ${STEP_TIMEOUT}s") ;;
  *) unknowns+=("pytest exited $code") ;;
esac

if ((${#failures[@]})); then
  message="$(join '; ' "${failures[@]}")"
  if ((${#unknowns[@]})); then
    message+=" (also could not tell: $(join '; ' "${unknowns[@]}"))"
  fi
  verdict FAIL "$message at $SHA"
  exit 1
fi
if ((${#unknowns[@]})); then
  verdict UNKNOWN "$(join '; ' "${unknowns[@]}") at $SHA"
  exit 1
fi
verdict PASS "$tests; ruff, ruff format and mypy clean at $SHA"
exit 0
