// Copyright 2013, 2019 Kevin Reid and the ShinySDR contributors
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

// WebGL definitions part of both vertex and fragment shaders for the spectrum graph (panadapter) and waterfall displays.

// Luminance texture storing spectrum data. S axis = frequency, T axis = time (as a circular buffer).
uniform sampler2D spectrumDataTexture;

// One-dimensional (width = 1) texture containing, for each line of the spectrumDataTexture, the center frequency of that line.
// If USE_FLOAT_TEXTURE is true, this is a float-valued luminance texture. Otherwise, the value is packed into the 8-bit components in (msb)ABGR(lsb) order.
uniform sampler2D centerFreqHistory;

// The center frequency currently active; determines the center of the viewport in frequency space.
uniform highp float currentFreq;

// Horizontal axis scale. TODO: explain in what units.
uniform mediump float freqScale;

// Look up and unpack a value from centerFreqHistory.
// point's first component is ignored and second component is the position in history.
// TODO: Cross-reference how history positions are defined.
highp float getFreqOffset(highp vec2 point) {
  // Coordinates for sampling centerFreqHistory. Must do our own wrapping because the wrap mode is CLAMP_TO_EDGE — TODO: Why can't we use REPEAT mode?
  point = vec2(0.0, mod(point.t, 1.0));
  
#if USE_FLOAT_TEXTURE
  // Direct lookup.
  highp float historyFreq = texture2D(centerFreqHistory, point).r;
#else
  // Unpack from bytes.
  highp vec4 historyFreqVec = texture2D(centerFreqHistory, point);
  highp float historyFreq =
    (((historyFreqVec.a * 255.0 * 256.0
     + historyFreqVec.b * 255.0) * 256.0
     + historyFreqVec.g * 255.0) * 256.0 
     + historyFreqVec.r * 255.0);
#endif
  
  return currentFreq - historyFreq;
}
