varying highp vec2 v_lonlat;
varying highp vec3 v_position;
uniform sampler2D texture;
uniform lowp vec3 sun;

void main(void) {
  lowp vec4 texture = texture2D(texture, mod(v_lonlat + vec2(180.0, 90.0), 360.0) * vec2(1.0/360.0, -1.0/180.0) + vec2(0.0, 1.0));
   lowp float light = mix(1.0, clamp(dot(v_position, sun) * 10.0 + 1.0, 0.0, 1.0), 0.25);   gl_FragColor = vec4(texture.rgb * light, texture.a);
}
