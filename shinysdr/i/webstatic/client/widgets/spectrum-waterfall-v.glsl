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

// Position of fragment in texture space (0 = lowest visible frequency / lowest value, 1 = highest visible frequency / highest value) after zoom is applied.
varying highp vec2 v_position;

// T coordinate of the most recently written line in spectrumDataTexture (see spectrum-common.glsl).
uniform highp float scroll;

// Zoom parameters. xTranslate is the texture-space left/lowest-frequency edge and xScale is the span; xTranslate and xTranslate + xScale are between 0 and 1.
// TODO: The values 'xZero' used by the graph shader and 'xTranslate' used by the waterfall shader differ by a half-texel. Reconcile or name them better for clarity -- or convert this shader to take a transformation matrix.
uniform highp float xTranslate, xScale;

// Vertical axis scale expressed as the display height divided by spectrumDataTexture's height.
uniform highp float yScale;

void main(void) {
  gl_Position = position;
  
  // TODO: Use a single input matrix instead of computing it on the fly -- if that turns out tidier.
  // Matrix converting normalized device coordinates to texture coordinates.
  mat3 viewToTexture = mat3(0.5, 0.0, 0.0, 0.0, 0.5, 0.0, 0.5, 0.5, 1.0);
  // Matrices applying frequency-axis zoom and vertical pixel-oriented scale.
  // Both result in viewing a smaller portion of spectrumDataTexture.
  mat3 zoom = mat3(xScale, 0.0, 0.0, 0.0, 1.0, 0.0, xTranslate, 0.0, 1.0);
  mat3 applyYScale = mat3(1.0, 0.0, 0.0, 0.0, yScale, 0.0, 0.0, -yScale, 1.0);
  // Final combined matrix
  mat3 viewMatrix = applyYScale * zoom * viewToTexture;
  
  // Apply view matrix and buffer scrolling to determine coordinate system used by fragment shader.
  v_position = (viewMatrix * position.xyw).xy + vec2(0.0, scroll);
}
