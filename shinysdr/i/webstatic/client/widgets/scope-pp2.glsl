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
uniform mediump float intensity;
uniform mediump float invgamma;
uniform mediump float kernel[diameter];

void main(void) {
  highp vec3 sum = vec3(0.0);
  for (int ky = 0; ky < diameter; ky++) {
    sum += kernel[ky] * texture2D(pp_texture, pp_texcoord + vec2(0.0, float(ky - radius)) / pp_size).rgb;
  }
  gl_FragColor = vec4(pow(intensity * sum, vec3(invgamma)) * vec3(0.1, 1.0, 0.5), 1.0);
}
