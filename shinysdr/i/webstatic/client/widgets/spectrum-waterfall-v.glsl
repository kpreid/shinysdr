// Copyright 2013, 2015, 2016 Kevin Reid and the ShinySDR contributors
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

attribute vec4 position;
varying highp vec2 v_position;

// T coordinate of the most recently written line in 'data'.
uniform highp float scroll;

uniform highp float xTranslate, xScale;
uniform highp float yScale;

void main(void) {
// TODO use a single input matrix instead of this
  mat3 viewToTexture = mat3(0.5, 0.0, 0.0, 0.0, 0.5, 0.0, 0.5, 0.5, 1.0);
  mat3 zoom = mat3(xScale, 0.0, 0.0, 0.0, 1.0, 0.0, xTranslate, 0.0, 1.0);
  mat3 applyYScale = mat3(1.0, 0.0, 0.0, 0.0, yScale, 0.0, 0.0, -yScale, 1.0);
  mat3 viewMatrix = applyYScale * zoom * viewToTexture;
  gl_Position = position;
  v_position = (viewMatrix * position.xyw).xy + vec2(0.0, scroll);
}
