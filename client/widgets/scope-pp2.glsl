const int diameter = radius * 2 + 1;
uniform mediump float intensity;
uniform mediump float invgamma;
uniform mediump float kernel[diameter];

void main(void) {
  highp vec3 sum = vec3(0.0);
  for (int ky = 0; ky < diameter; ky++) {
    sum += kernel[ky] * texture2D(pp_texture, pp_texcoord + vec2(0.0, float(ky - radius)) / pp_size).rgb;
  }
  gl_FragColor = vec4(pow(intensity * sum, vec3(invgamma)) * vec3(0.1, 1.0, 0.5), 1.0);
}
