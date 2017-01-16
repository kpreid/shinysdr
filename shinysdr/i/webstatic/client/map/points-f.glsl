varying lowp vec3 v_texcoordAndOpacity;
varying mediump vec4 v_pickingColor;
uniform sampler2D labels;
uniform bool picking;

void main(void) {
  lowp vec2 texcoord = v_texcoordAndOpacity.xy;
  lowp float opacity = v_texcoordAndOpacity.z;
  // Texture is premultiplied alpha.
  gl_FragColor = picking ? v_pickingColor : opacity * texture2D(labels, texcoord);
  if ((picking ? v_texcoordAndOpacity.z : gl_FragColor.a) < 0.01) discard;
}
