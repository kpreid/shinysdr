// Copyright 2015, 2016, 2017, 2019 Kevin Reid and the ShinySDR contributors
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

// WebGL fragment shader for drawing the map's features.

// Packed vector: Texture's UV coordinates (2) and overall opacity (1).
varying lowp vec3 v_texcoordAndOpacity;

// Color to draw for picking purposes; not modified by opacity.
varying mediump vec4 v_pickingColor;

// Texture to draw; premultiplied alpha.
uniform sampler2D labels;

// Whether we are drawing in picking mode (draw v_pickingColor instead of the texture).
uniform bool picking;

void main(void) {
  lowp vec2 texcoord = v_texcoordAndOpacity.xy;
  lowp float opacity = v_texcoordAndOpacity.z;
  
  // Draw either the picking color or the texture.
  gl_FragColor = picking ? v_pickingColor : opacity * texture2D(labels, texcoord);
  
  // If not picking, discard nearly invisible areas; if picking, the entire area we're drawing counts unless it's nearly invisible (so that clicking on holes inside text labels counts).
  if ((picking ? opacity : gl_FragColor.a) < 0.01) discard;
}
