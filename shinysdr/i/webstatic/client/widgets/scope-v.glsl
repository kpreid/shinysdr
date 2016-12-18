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
