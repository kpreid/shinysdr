attribute vec4 position;
uniform mediump float xZero, xScale;
varying highp vec2 v_position;

void main(void) {
  gl_Position = position;
  mediump vec2 basePos = (position.xy + vec2(1.0)) / 2.0;
  v_position = vec2(xScale * basePos.x + xZero, basePos.y);
}
