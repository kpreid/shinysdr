#!/bin/sh

# This script will download all the dependencies for ShinySDR which are client-only, and therefore simply files we serve, as opposed to Python or C libraries that might have more complex dependencies themselves.

set -e

# fetches jasmine
git submodule update --init

(cd shinysdr/deps/ &&
  wget -N http://requirejs.org/docs/release/2.1.9/comments/require.js)

ol_version="2.13.1"
ol_file="OpenLayers-$ol_version.tar.gz"
ol_unpack="OpenLayers-$ol_version"
(cd shinysdr/deps/ &&
  wget -N "https://github.com/openlayers/openlayers/releases/download/release-$ol_version/$ol_file" &&
  tar zxf "$ol_file" &&
  rm -rf openlayers &&
  mkdir openlayers &&
  mv "$ol_unpack/img" "$ol_unpack/theme" "$ol_unpack"/OpenLayers*.js openlayers/ &&
  rm -rf "$ol_unpack" "$ol_file")
