// Copyright 2015, 2016, 2017 Kevin Reid and the ShinySDR contributors
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

varying lowp vec3 v_texcoordAndOpacity;
varying mediump vec4 v_pickingColor;
uniform sampler2D labels;
uniform bool picking;

void main(void) {
  lowp vec2 texcoord = v_texcoordAndOpacity.xy;
  lowp float opacity = v_texcoordAndOpacity.z;
  // Texture is premultiplied alpha.
  gl_FragColor = picking ? v_pickingColor : opacity * texture2D(labels, texcoord);
  if ((picking ? v_texcoordAndOpacity.z : gl_FragColor.a) < 0.01) discard;
}
