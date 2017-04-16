#!/bin/sh

# JS lint
jshint shinysdr/i/{webstatic,webparts}

# Python lint
# pylint is last because it is the slowest linter.
flake8 --exclude=deps shinysdr/ *.py
pylint --rcfile pylintrc shinysdr
