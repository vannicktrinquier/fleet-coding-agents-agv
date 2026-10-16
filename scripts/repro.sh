#!/usr/bin/env bash
# fleet/repro: shows that a bug-fix PR comes with tests that catch the bug.
#
# The tests the PR adds or modifies (tests/**/test_*.py changed since the merge
# base with the target branch) must
#   1. pass at the head commit, and
#   2. fail (pytest exit 1) once everything outside tests/ is put back to the
#      merge base.
#
# Prints exactly one "fleet-verdict" annotation, like ci_evidence.sh, and exits 0
# only on PASS:
#   PASS     head = 0 and base = 1
#   FAIL     the tests fail at head, or they pass on the base
#   UNKNOWN  no changed tests, a collection error, a crash or a timeout
# Needs the full history (actions/checkout with fetch-depth: 0) and a clean
# working tree. The working tree is put back to HEAD on exit.
#
# Environment:
#   FLEET_BASE_REF      ref to compare against (default: origin/$GITHUB_BASE_REF, else origin/main)
#   FLEET_VENV          virtualenv holding pytest (default: .venv, see `make setup`)
#   FLEET_STEP_TIMEOUT  seconds allowed per pytest run (default: 300)
set -uo pipefail

main() {
  cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1

  BIN="${FLEET_VENV:-.venv}/bin"
  BASE_REF="${FLEET_BASE_REF:-origin/${GITHUB_BASE_REF:-main}}"
  STEP_TIMEOUT="${FLEET_STEP_TIMEOUT:-300}"
  TOKEN="fleet-$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n')"
  LOGS="$(mktemp -d)"
  HEAD_SHA=""
  rewritten=0
  verdict_sent=0
  export PYTHONDONTWRITEBYTECODE=1
  trap finish EXIT

  if [[ ! -x "$BIN/pytest" ]]; then
    verdict UNKNOWN "$BIN/pytest is missing (did 'make setup' succeed?)"
    exit 1
  fi
  if ! HEAD_SHA="$(git rev-parse --verify HEAD 2>/dev/null)"; then
    verdict UNKNOWN "not inside a git checkout"
    exit 1
  fi
  if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
    verdict UNKNOWN "the working tree has uncommitted changes at ${HEAD_SHA:0:12}"
    exit 1
  fi
  local base
  if ! base="$(git merge-base "$BASE_REF" "$HEAD_SHA" 2>/dev/null)"; then
    verdict UNKNOWN "no merge base between $BASE_REF and ${HEAD_SHA:0:12} (needs fetch-depth: 0)"
    exit 1
  fi

  mapfile -t tests < <(
    git diff --name-only --no-renames --diff-filter=AM "$base" "$HEAD_SHA" -- \
      ':(glob)tests/**/test_*.py'
  )
  if ((${#tests[@]} == 0)); then
    verdict UNKNOWN "no added or modified tests/**/test_*.py since the merge base ${base:0:12}"
    exit 1
  fi
  printf 'Changed tests since %s:\n' "${base:0:12}"
  printf '  %s\n' "${tests[@]}"

  run_tests head "${tests[@]}"
  local head_code=$?
  case "$head_code" in
    0) ;;
    1)
      verdict FAIL "the changed tests fail at head ${HEAD_SHA:0:12}: $(summary head)"
      exit 1
      ;;
    124 | 137)
      verdict UNKNOWN "pytest timed out after ${STEP_TIMEOUT}s at head ${HEAD_SHA:0:12}"
      exit 1
      ;;
    *)
      verdict UNKNOWN "pytest exited $head_code at head ${HEAD_SHA:0:12}: $(summary head)"
      exit 1
      ;;
  esac

  # Everything outside tests/ goes back to the merge base, including files the
  # PR added (removed) or deleted (restored).
  rewritten=1
  git checkout --quiet "$base" -- . ':(exclude)tests'
  mapfile -t added < <(
    git diff --name-only --no-renames --diff-filter=A "$base" "$HEAD_SHA" -- . ':(exclude)tests'
  )
  if ((${#added[@]})); then
    rm -f -- "${added[@]}"
  fi

  run_tests base "${tests[@]}"
  local base_code=$?
  case "$base_code" in
    1)
      verdict PASS "${#tests[@]} changed test file(s) pass at head ${HEAD_SHA:0:12} and fail on base ${base:0:12}"
      exit 0
      ;;
    0)
      verdict FAIL "new tests pass on base ${base:0:12}, they don't catch the bug"
      exit 1
      ;;
    124 | 137)
      verdict UNKNOWN "pytest timed out after ${STEP_TIMEOUT}s on base ${base:0:12}"
      exit 1
      ;;
    *)
      verdict UNKNOWN "pytest exited $base_code on base ${base:0:12} (2 = collection error), so it cannot tell whether the tests catch the bug"
      exit 1
      ;;
  esac
}

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
    printf '### fleet/repro: %s\n\n%s\n' "$kind" "$message" >>"$GITHUB_STEP_SUMMARY"
  fi
  verdict_sent=1
}

finish() {
  local code=$?
  if ((rewritten)); then
    git reset --quiet --hard "$HEAD_SHA"
  fi
  rm -rf "$LOGS"
  if ((!verdict_sent)); then
    verdict UNKNOWN "repro.sh stopped before reaching a verdict (exit $code)"
    exit 1
  fi
  exit "$code"
}

# run_tests <label> <test files...>
run_tests() {
  local label="$1"
  shift
  echo "::group::pytest at $label"
  echo "::stop-commands::$TOKEN"
  timeout --kill-after=15 "$STEP_TIMEOUT" "$BIN/pytest" -q -p no:cacheprovider -- "$@" 2>&1 \
    | tee "$LOGS/$label.log"
  local code=${PIPESTATUS[0]}
  echo "::$TOKEN::"
  echo "::endgroup::"
  return "$code"
}

summary() {
  grep -E '[0-9]+ (passed|failed|errors?|skipped|xfailed|xpassed|deselected)|no tests ran' \
    "$LOGS/$1.log" | tail -n 1 | sed -E 's/^=+ //; s/ =+$//'
}

main "$@"
