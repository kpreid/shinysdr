const int diameter = radius * 2 + 1;
uniform mediump float kernel[diameter];

void main(void) {
  highp vec3 sum = vec3(0.0);
  for (int kx = 0; kx < diameter; kx++) {
    sum += kernel[kx] * texture2D(pp_texture, pp_texcoord + vec2(float(kx - radius), 0.0) / pp_size).rgb;
  }
  gl_FragColor = vec4(sum, 1.0);
}
