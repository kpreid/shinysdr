// Copyright 2013, 2016 Kevin Reid and the ShinySDR contributors
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

uniform sampler2D data;
uniform mediump float xScale, xRes, yRes, valueZero, valueScale;
uniform highp float scroll;
uniform highp float historyStep;
uniform lowp float avgAlpha;
varying highp vec2 v_position;
const int stepRange = 2;
highp vec2 stepStep;  // initialized in main
const lowp float stepSumScale = 1.0/(float(stepRange) * 2.0 + 1.0);
const int averaging = 32;

mediump vec4 cmix(mediump vec4 before, mediump vec4 after, mediump float a) {
  return mix(before, after, clamp(a, 0.0, 1.0));
}
mediump vec4 cut(mediump float boundary, mediump float offset, mediump vec4 before, mediump vec4 after) {
  mediump float case = (boundary - v_position.y) * yRes + offset;
  return cmix(before, after, case);
}
lowp float filler(highp float value) {
  return cmix(vec4(0.0), vec4(value), value).r;
}
mediump vec4 line(lowp float plus, lowp float average, lowp float intensity, mediump vec4 bg, mediump vec4 fg) {
  return cmix(bg, cut(average + plus, 0.5, bg, cut(average, -0.5, fg, bg)), intensity);
}
highp vec2 coords(highp float framesBack) {
  // compute texture coords -- must be moduloed aterward
  return vec2(v_position.x, scroll - (framesBack + 0.5) * historyStep);
}
highp float pointValueAt(highp vec2 c) {
  return valueZero + valueScale * texture2D(data, mod(c, 1.0)).r;
}
highp float shiftedPointValueAt(highp vec2 c) {
  highp float offset = getFreqOffset(c) * freqScale;
  return pointValueAt(c + vec2(offset, 0.0));
}
highp float pointAverageAt(highp vec2 c) {
  lowp float average = 0.0;
  for (int t = averaging - 1; t >= 0; t--) {
  // note: FIR emulation of IIR filter because IIR is what the non-GL version uses
      average = mix(average, shiftedPointValueAt(c + vec2(0.0, -float(t) * historyStep)), t >= averaging - 1 ? 1.0 : avgAlpha);
    }
  return average;
}
void fetchSmoothValueAt(highp float t, out mediump float plus, out mediump float average) {
  highp vec2 texLookup = coords(t);
  average = 0.0;
  mediump float peak = -1.0;
  mediump float valley = 2.0;
  for (int i = -stepRange; i <= stepRange; i++) {
    mediump float value = shiftedPointValueAt(texLookup + stepStep * float(i));
    average += value;
    peak = max(peak, value);
    valley = min(valley, value);
  }
  average *= stepSumScale;
  plus = peak - average;
}
void fetchSmoothAverageValueAt(out mediump float plus, out mediump float average) {
  highp vec2 texLookup = coords(0.0);
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
lowp float accumFillIntensity() {
  lowp float accumFill = 0.0;
  for (highp float i = 0.0; i < float(averaging); i += 1.0) {
    lowp float average;
    lowp float plus;
    fetchSmoothValueAt(i, plus, average);
    accumFill += cut(average, 1.0, vec4(0.0), vec4(average)).r;
  }
  return accumFill * (1.0 / float(averaging));
}

void main(void) {
  // initialize globals
  stepStep = vec2(xScale / xRes * (1.0 / float(stepRange)), 0.0);
  
  mediump float aaverage;
  mediump float aplus;
  fetchSmoothAverageValueAt(aplus, aaverage);
  mediump float laverage;
  mediump float lplus;
  fetchSmoothValueAt(0.0, lplus, laverage);
  gl_FragColor = vec4(0.0, 0.5, 1.0, 1.0) * accumFillIntensity() * 3.0;
  gl_FragColor = line(aplus, aaverage, 0.75, gl_FragColor, vec4(0.0, 1.0, 0.6, 1.0));
  gl_FragColor = line(lplus, laverage, max(0.0, laverage - aaverage) * 4.0, gl_FragColor, vec4(1.0, 0.2, 0.2, 1.0));
}
