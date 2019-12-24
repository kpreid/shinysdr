// Copyright 2013 Kevin Reid and the ShinySDR contributors
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

uniform sampler2D centerFreqHistory;
uniform highp float currentFreq;
uniform mediump float freqScale;

highp float getFreqOffset(highp vec2 c) {
  c = vec2(0.0, mod(c.t, 1.0));
#if USE_FLOAT_TEXTURE
  return currentFreq - texture2D(centerFreqHistory, c).r;
#else
  highp vec4 hFreqVec = texture2D(centerFreqHistory, c);
  return currentFreq - (((hFreqVec.a * 255.0 * 256.0 + hFreqVec.b * 255.0) * 256.0 + hFreqVec.g * 255.0) * 256.0 + hFreqVec.r * 255.0);
#endif
}
