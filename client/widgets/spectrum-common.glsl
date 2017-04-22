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
