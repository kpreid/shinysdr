#!/bin/sh

# This script will download all the dependencies for ShinySDR which are client-only, and therefore simply files we serve, as opposed to Python or C libraries that might have more complex dependencies themselves.

set -e

# fetches jasmine
git submodule update --init

(cd shinysdr/deps/ &&
  wget -N http://requirejs.org/docs/release/2.1.9/comments/require.js)
