#!/bin/sh

flake8 --exclude=deps shinysdr/ *.py
pylint --rcfile pylintrc shinysdr
jshint shinysdr/i/{webstatic,webparts}
