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

attribute mediump float relativeTime;
uniform float interpStep;
uniform mat4 projection;
uniform mediump float bufferCutPoint;
uniform sampler2D scopeData;
varying lowp float v_z;

// vertex shader scraps for FIR filtering -- couldn't get it to work but this should still be the skeleton of it
//  uniform mediump float filter[37];
//  mediump vec2 rawsignal(mediump float tsub) {  // zero-stuffed signal
//    return mod(tsub / interpStep, 10.0) < 1.00
//        ? texture2D(scopeData, vec2(tsub, 0.5)).ra
//        : vec2(0.0);
//  }
//    for (int i = -18; i <= 18; i++) {
//      signal += filter[i] * rawsignal(time + float(i) * interpStep);
//    }

void main(void) {
  mediump float bufferTime = mod(bufferCutPoint + relativeTime, 1.0);
  gl_PointSize = 1.0;
  mediump vec2 signal = texture2D(scopeData, vec2(bufferTime, 0.5)).ra;
  vec4 basePos = vec4(signal, relativeTime * 2.0 - 1.0, 1.0);
  vec4 projected = basePos * projection;
  gl_Position = vec4(clamp(projected.x, -0.999, 0.999), clamp(projected.y, -0.999, 0.999), 0.0, projected.w);  // show over-range in x and y and don't clip to z
  v_z = (projected.z / projected.w) / 2.0 + 0.5;  // 0-1 range instead of -1-1
}
