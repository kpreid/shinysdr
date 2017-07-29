#!/bin/sh

# This script will download all the dependencies for ShinySDR which are client-only, and therefore simply files we serve, as opposed to Python or C libraries that might have more complex dependencies themselves.

set -eu

# fetches jasmine
git submodule update --init

(cd shinysdr/deps/ &&
  wget -N http://requirejs.org/docs/release/2.1.22/comments/require.js &&
  wget -N https://raw.githubusercontent.com/requirejs/text/646db27aaf2236cea92ac4107f32cbe5ae7a8d3a/text.js)
