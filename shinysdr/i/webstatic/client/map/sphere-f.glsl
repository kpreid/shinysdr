// Copyright 2015, 2016 Kevin Reid and the ShinySDR contributors
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

varying highp vec2 v_lonlat;
varying highp vec3 v_position;
uniform sampler2D texture;
uniform lowp vec3 sun;

void main(void) {
  lowp vec4 texture = texture2D(texture, mod(v_lonlat + vec2(180.0, 90.0), 360.0) * vec2(1.0/360.0, -1.0/180.0) + vec2(0.0, 1.0));
   lowp float light = mix(1.0, clamp(dot(v_position, sun) * 10.0 + 1.0, 0.0, 1.0), 0.25);   gl_FragColor = vec4(texture.rgb * light, texture.a);
}
