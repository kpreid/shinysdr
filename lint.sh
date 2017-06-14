#!/bin/bash

set -e
declare -a errors

function linter {
  echo "------ $0: Running $1"
  "$@" || errors+=("$1")
}

# JS lint
linter jshint shinysdr/i/{webstatic,webparts}

# Python lint
# pylint is last because it is the slowest linter.
linter flake8 --exclude=deps shinysdr/ *.py
linter pylint --rcfile pylintrc shinysdr

# Print summary and return status code
if [[ ${#errors[*]} -ne 0 ]]; then
  echo "------ $0: Errors found by: ${errors[@]}"
  exit 1
fi
