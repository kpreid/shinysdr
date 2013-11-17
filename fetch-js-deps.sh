#!/bin/sh

# This script will download all the dependencies for ShinySDR which are client-only, and therefore simply files we serve, as opposed to Python or C libraries that might have more complex dependencies themselves.

set -e

# fetches jasmine
git submodule update --init

(cd shinysdr/deps/ &&
  wget -N http://requirejs.org/docs/release/2.1.9/comments/require.js)

ol_version="2.13.1"
ol_file="OpenLayers-$ol_version.tar.gz"
(cd shinysdr/deps/ &&
  wget -N "http://openlayers.org/download/$ol_file" &&
  tar zxf "$ol_file" &&
  rm -r openlayers &&
  mkdir openlayers &&
  mv "OpenLayers-$ol_version/"{img,theme,OpenLayers*.js} openlayers/ &&
  rm -rf "OpenLayers-$ol_version/" "$ol_file")
