attribute vec3 position;
attribute vec4 velocityAndTimestamp;
attribute vec3 billboard;
attribute vec3 texcoordAndOpacity;
attribute vec4 pickingColor;
uniform highp float time;
uniform mat4 projection;
uniform vec3 billboardScale;
varying lowp vec3 v_texcoordAndOpacity;
varying mediump vec4 v_pickingColor;  // TODO figure out necessary resolution

void main(void) {
  vec3 velocity = velocityAndTimestamp.xyz;
  highp float timestamp = velocityAndTimestamp.w;
  highp float speed = length(velocity);
  vec3 forward = speed > 0.0 ? normalize(velocity) : vec3(0.0);
  highp float distance = speed * (time - timestamp);
  vec3 currentPosition = cos(distance) * position + sin(distance) * forward;
  gl_Position = vec4(currentPosition, 1.0) * projection + vec4(billboard * billboardScale, 0.0);
  v_texcoordAndOpacity = texcoordAndOpacity;
  v_pickingColor = pickingColor;
  velocity;
}
