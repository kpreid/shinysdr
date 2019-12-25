// Copyright 2013, 2016, 2019 Kevin Reid and the ShinySDR contributors
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

// Luminance texture storing spectrum data. S axis = frequency, T axis = time (as a circular buffer).
uniform sampler2D data;

// Zoom and data scale parameters. TODO: Split these out and explain more.
uniform mediump float xScale, xRes, yRes, valueZero, valueScale;

// T coordinate of the most recently written line in 'data'.
uniform highp float scroll;

// Texture-space size of one time step (= 1 / data's size in the T axis).
uniform highp float historyStep;

// IIR filter coefficient for averaging of the graph line position.
uniform lowp float avgAlpha;

// How far in history to look for data entering the average.
const int averaging = 32;

// Position of fragment in texture space (0 = lowest visible frequency / lowest value, 1 = highest visible frequency / highest value) after zoom is applied.
varying highp vec2 v_position;

// Number of steps (-stepRange...+stepRange) to look along the frequency axis in our attempt to draw a smooth non-aliased line. TODO: Explain better.
const int stepRange = 2;

// Scale (on the S axis) of steps to take according to stepRange.
highp vec2 stepStep;  // initialized in main

// Coefficient to scale sum of steps by.
const lowp float stepSumScale = 1.0/(float(stepRange) * 2.0 + 1.0);


// As builtin mix() except that it clamps the interpolation position 'a' (and is not overloaded).
mediump vec4 cmix(mediump vec4 before, mediump vec4 after, mediump float a) {
  return mix(before, after, clamp(a, 0.0, 1.0));
}

// Compute a color based on vertical position.
//   boundary: y coordinate of the cut in (0...1) space
//   offset: screen-space (1 unit = 1 pixel) offset to be added to 'boundary'
//   before: color above the cut
//   after: color below the cut
mediump vec4 cut(mediump float boundary, mediump float offset, mediump vec4 before, mediump vec4 after) {
  mediump float case = (boundary - v_position.y) * yRes + offset;
  return cmix(before, after, case);
}

// Paint a line.
//   plus: amount to thicken the line by to account for slope, in the positive direction
//   average: y coordinate of the line in (0...1) space
//   intensity: opacity of the line
//   bg: color for not-on-the-line
//   fg: color of the line
mediump vec4 line(lowp float plus, lowp float average, lowp float intensity, mediump vec4 bg, mediump vec4 fg) {
  return cmix(bg, cut(average + plus, 0.5, bg, cut(average, -0.5, fg, bg)), intensity);
}

// Compute texture coordinates for the 'data' texture, based on the current fragment position (v_position) and how many time steps back from 'now' we want to query (framesBack).
// Does not account for frequency offsets.
// The result is not guaranteed to be in (0...1); apply modulo when needed.
highp vec2 dataCoordsForTimeBack(highp float framesBack) {
  return vec2(v_position.x, scroll - (framesBack + 0.5) * historyStep);
}

// Fetch a data value given post-zooming screen coordinates (still in 0...1 range but with frequency offset applied).
// Applies scaling so that the result is in the intended display range (0...1) (individual values might be out of range).
highp float shiftedPointValueAt(highp vec2 c) {
  highp float offset = getFreqOffset(c) * freqScale;
  highp vec2 offsetPoint = c + vec2(offset, 0.0);
  return valueZero + valueScale * texture2D(data, mod(offsetPoint, 1.0)).r;
}

// As shiftedPointValueAt, but with the time average (specified by uniforms) applied.
highp float pointAverageAt(highp vec2 c) {
  lowp float average = 0.0;
  for (int t = averaging - 1; t >= 0; t--) {
  // note: FIR emulation of IIR filter because IIR is what the non-GL version uses
      average = mix(average, shiftedPointValueAt(c + vec2(0.0, -float(t) * historyStep)), t >= averaging - 1 ? 1.0 : avgAlpha);
    }
  return average;
}

// Fetch a data value for a given time, smoothed in the frequency axis in case of zooming.
//   t: number of time steps back to look (0 = now).
//   plus: out parameter for the 'plus' value to pass to line()
//   smoothed: out parameter holding smoothed value
void fetchSmoothValueAt(highp float t, out mediump float plus, out mediump float smoothed) {
  highp vec2 texLookup = dataCoordsForTimeBack(t);
  smoothed = 0.0;
  mediump float peak = -1.0;
  mediump float valley = 2.0;
  for (int i = -stepRange; i <= stepRange; i++) {
    mediump float value = shiftedPointValueAt(texLookup + stepStep * float(i));
    smoothed += value;
    peak = max(peak, value);
    valley = min(valley, value);
  }
  smoothed *= stepSumScale;
  plus = peak - smoothed;
}

// As fetchSmoothValueAt, but with the time average (specified by uniforms) applied.
void fetchSmoothAverageValueAt(out mediump float plus, out mediump float average) {
  highp vec2 texLookup = dataCoordsForTimeBack(0.0);
  average = 0.0;
  mediump float peak = -1.0;
  mediump float valley = 2.0;
  for (int i = -stepRange; i <= stepRange; i++) {
    mediump float value = pointAverageAt(texLookup + stepStep * float(i));
    average += value;
    peak = max(peak, value);
    valley = min(valley, value);
  }
  average *= stepSumScale;
  plus = peak - average;
}

// Compute, for the current pixel, the intensity of under-the-curve fill color to use.
// Each historical frame is taken as its own curve and the resulting intensities are averaged.
lowp float accumFillIntensity() {
  lowp float accumFill = 0.0;
  for (highp float i = 0.0; i < float(averaging); i += 1.0) {
    lowp float value;
    lowp float unused_plus;
    fetchSmoothValueAt(i, unused_plus, value);
    accumFill += cut(value, 1.0, vec4(0.0), vec4(value)).r;
  }
  return accumFill * (1.0 / float(averaging));
}

void main(void) {
  // initialize globals
  stepStep = vec2(xScale / xRes * (1.0 / float(stepRange)), 0.0);
  
  // Fetch data for line drawing.
  mediump float aaverage;
  mediump float aplus;
  fetchSmoothAverageValueAt(aplus, aaverage);
  mediump float laverage;
  mediump float lplus;
  fetchSmoothValueAt(0.0, lplus, laverage);
  
  // Paint the under-the-curve fill.
  gl_FragColor = vec4(0.0, 0.5, 1.0, 1.0) * accumFillIntensity() * 3.0;
  
  // Paint the cyan average-level line.
  gl_FragColor = line(aplus, aaverage, 0.75, gl_FragColor, vec4(0.0, 1.0, 0.6, 1.0));
  
  // Paint the transparent red peak-level line.
  // The line becomes transparent where it is close to the average line.
  gl_FragColor = line(
      lplus,
      laverage,
      max(0.0, laverage - aaverage) * 4.0,
      gl_FragColor,
      vec4(1.0, 0.2, 0.2, 1.0));
}
