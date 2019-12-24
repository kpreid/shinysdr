// Copyright 2014, 2016 Kevin Reid and the ShinySDR contributors
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

const int diameter = radius * 2 + 1;
uniform mediump float kernel[diameter];

void main(void) {
  highp vec3 sum = vec3(0.0);
  for (int kx = 0; kx < diameter; kx++) {
    sum += kernel[kx] * texture2D(pp_texture, pp_texcoord + vec2(float(kx - radius), 0.0) / pp_size).rgb;
  }
  gl_FragColor = vec4(sum, 1.0);
}
