attribute vec4 position;
varying highp vec2 v_position;
uniform highp float scroll;
uniform highp float xTranslate, xScale;
uniform highp float yScale;

void main(void) {
// TODO use a single input matrix instead of this
  mat3 viewToTexture = mat3(0.5, 0.0, 0.0, 0.0, 0.5, 0.0, 0.5, 0.5, 1.0);
  mat3 zoom = mat3(xScale, 0.0, 0.0, 0.0, 1.0, 0.0, xTranslate, 0.0, 1.0);
  mat3 applyYScale = mat3(1.0, 0.0, 0.0, 0.0, yScale, 0.0, 0.0, -yScale, 1.0);
  mat3 viewMatrix = applyYScale * zoom * viewToTexture;
  gl_Position = position;
  v_position = (viewMatrix * position.xyw).xy + vec2(0.0, scroll);
}
