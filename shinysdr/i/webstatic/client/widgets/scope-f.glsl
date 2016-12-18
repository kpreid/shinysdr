varying lowp float v_z;
uniform mediump float persistence_gamma;
void main(void) {
  // TODO: Experiment with ways we can use the currently-wasted three different components.
  // Note: the pow() here (rather than exponential decay) is not realistic but seems to produce good results.
  gl_FragColor = vec4(vec3(pow(v_z, persistence_gamma)), 1.0);
}
