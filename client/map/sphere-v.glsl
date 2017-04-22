attribute mediump vec3 position;
attribute highp vec2 lonlat;
uniform highp mat4 projection;
varying highp vec2 v_lonlat;
varying highp vec3 v_position;

void main(void) {
  gl_Position = vec4(position, 1.0) * projection;
  v_lonlat = lonlat;
  v_position = position;
}
