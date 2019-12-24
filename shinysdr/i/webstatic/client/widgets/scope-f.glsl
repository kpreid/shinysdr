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

varying lowp float v_z;
uniform mediump float persistence_gamma;
void main(void) {
  // TODO: Experiment with ways we can use the currently-wasted three different components.
  // Note: the pow() here (rather than exponential decay) is not realistic but seems to produce good results.
  gl_FragColor = vec4(vec3(pow(v_z, persistence_gamma)), 1.0);
}
