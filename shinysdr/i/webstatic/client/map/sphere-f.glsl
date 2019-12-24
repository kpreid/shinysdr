// Copyright 2015, 2016, 2019 Kevin Reid and the ShinySDR contributors
// 
// This file is part of ShinySDR.
// 
// ShinySDR is free software: you can redistribute it and/or modify
// it under the terms of the GNU General Public License as published by
// the Free Software Foundation, either version 3 of the License, or
// (at your option) any later version.
// 
// ShinySDR is distributed in the hope that it will be useful,
// but WITHOUT ANY WARRANTY; without even the implied warranty of
// MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
// GNU General Public License for more details.
// 
// You should have received a copy of the GNU General Public License
// along with ShinySDR.  If not, see <http://www.gnu.org/licenses/>.

// WebGL fragment shader for drawing the map's globe.

// Position being drawn in 3-dimensional coordinates.
varying highp vec3 v_position;

// Position in 2-dimensional coordinates (longitude, latitude); used to texture the sphere.
varying highp vec2 v_lonlat;

// Texture drawn on the sphere, in plate carrée projection.
uniform sampler2D texture;

// Position of the sun, in the same coordinates as v_position.
uniform lowp vec3 sun;

void main(void) {
  // Get surface color from texture by transforming v_lonlat into texture coordinates.
  lowp vec4 texture = texture2D(texture, 
      mod(v_lonlat + vec2(180.0, 90.0), 360.0) * vec2(1.0/360.0, -1.0/180.0)
      + vec2(0.0, 1.0));
  
  // Compute sunlight magnitude (not realistic, just enough to get a day side, night side, and terminator).
  lowp float light = mix(1.0, clamp(dot(v_position, sun) * 10.0 + 1.0, 0.0, 1.0), 0.25);
  
  gl_FragColor = vec4(texture.rgb * light, texture.a);
}
