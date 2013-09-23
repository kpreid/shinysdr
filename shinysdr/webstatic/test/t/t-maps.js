'use strict';

describe('maps', function () {
  describe('Map', function () {
    // TODO more tests
    it('exists', function () {
      expect(typeof shinysdr.maps).toBe('object');
      expect(typeof shinysdr.maps.Map).toBe('function');
    });
  });
});
