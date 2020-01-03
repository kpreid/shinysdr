// Copyright 2013, 2014, 2015, 2016, 2019 Kevin Reid and the ShinySDR contributors
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

// RGBA lookup table for gradient colors. S axis unused, T axis = scaled value.
uniform sampler2D gradient;

// Scale and offset to map spectrumDataTexture values to 'gradient' texture coordinates.
uniform mediump float gradientZero;
uniform mediump float gradientScale;

// Position of this fragment in spectrumDataTexture, before accounting for frequency offsets.
varying mediump vec2 v_position;

// Posible half-texel adjustment to align GL texture coordinates with where we want FFT bins to fall.
uniform highp float textureRotation;

void main(void) {
  highp vec2 texLookup = mod(v_position, 1.0);
  highp float freqOffset = getFreqOffset(texLookup) * freqScale;
  mediump vec2 shiftedDataCoordinates = texLookup + vec2(freqOffset, 0.0);
  
  if (shiftedDataCoordinates.x < 0.0 || shiftedDataCoordinates.x > 1.0) {
    // We're off the edge of the data; draw background instead of any data value.
    gl_FragColor = BACKGROUND_COLOR;
  } else {
    // Fetch data value.
    mediump float data = texture2D(spectrumDataTexture, shiftedDataCoordinates + vec2(textureRotation, 0.0)).r;
    
    // Fetch color from data texture.
    gl_FragColor = texture2D(gradient, vec2(0.5, gradientZero + gradientScale * data));
  }
}
