// Copyright 2013, 2015, 2016, 2019 Kevin Reid and the ShinySDR contributors
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

// Vertex position, in normalized device coordinates.
attribute vec4 position;

// Zoom parameters. xZero is the texture-space left/lowest-frequency edge and xScale is the span; xZero and xZero + xScale are between 0 and 1.
uniform mediump float xZero, xScale;

// Position of fragment in texture space (0 = lowest visible frequency, 1 = highest visible frequency) after zoom is applied.
varying highp vec2 v_position;

void main(void) {
  gl_Position = position;
  
  // Convert normalized device coordinates (-1...1) to texture coordinates (0...1).
  mediump vec2 basePos = (position.xy + vec2(1.0)) / 2.0;
  
  // Apply horizontal zoom.
  v_position = vec2(xScale * basePos.x + xZero, basePos.y);
}
