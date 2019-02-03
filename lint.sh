#!/bin/bash

set -eu

# --- Parse options

only_lang="${1:-all}"

# --- Prepare to lint

declare -a errors skips
errors=()
skips=()

function linter {
  local lang="$1"; shift
  local program="$1"; shift
  if [[ "x$only_lang" == "x$lang" || "x$only_lang" == "xall" ]]; then
    echo "------ $0: Running $program ($lang)"
    "$program" "$@" || errors+=("$program")
  else
    skips+=("$program")
  fi
}

# --- Run linters

# JS lint
linter js jshint shinysdr/i/{webstatic,webparts} shinysdr/plugins

# Python lint
# pylint is last because it is the slowest linter.
linter py flake8 --ignore=W191,W291,W293,W503,W504,E126,E128,E241,E501,E701 --exclude=deps shinysdr/ *.py
linter py pylint --rcfile pylintrc shinysdr

# --- Print summary and return status code

if [[ ${#errors[*]} -ne 0 ]]; then
  echo "------ $0: Errors found by: ${errors[@]}"
  exit 1
fi
if [[ ${#skips[*]} -ne 0 ]]; then
  echo "------ $0: Skipped: ${skips[@]}"
  exit 2
fi
