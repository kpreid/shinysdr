varying lowp vec3 v_texcoordAndOpacity;
varying mediump vec4 v_pickingColor;
uniform sampler2D labels;
uniform bool picking;

void main(void) {
  lowp float lineBrightness = v_texcoordAndOpacity.x;
  lowp float opacity = v_texcoordAndOpacity.z;
  gl_FragColor = picking ? v_pickingColor : v_texcoordAndOpacity.z * vec4(vec3(1.0 - lineBrightness), 1.0);
}
