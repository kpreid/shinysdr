'use strict';

describe('values', function () {
  describe('Range', function () {
    var Range = shinysdr.values.Range;
    function frange(subranges) {
      return new Range(subranges, false, false);
    }
    it('should round at the ends of simple ranges', function () {
      expect(frange([[1, 3]]).round(0, -1)).toBe(1);
      expect(frange([[1, 3]]).round(2, -1)).toBe(2);
      expect(frange([[1, 3]]).round(4, -1)).toBe(3);
      expect(frange([[1, 3]]).round(0, 1)).toBe(1);
      expect(frange([[1, 3]]).round(2, 1)).toBe(2);
      expect(frange([[1, 3]]).round(4, 1)).toBe(3);
    });
    it('should round in the gaps of split ranges', function () {
      expect(frange([[1, 2], [3, 4]]).round(2.4, 0)).toBe(2);
      expect(frange([[1, 2], [3, 4]]).round(2.4, -1)).toBe(2);
      expect(frange([[1, 2], [3, 4]]).round(2.4, +1)).toBe(3);
      expect(frange([[1, 2], [3, 4]]).round(2.6, -1)).toBe(2);
      expect(frange([[1, 2], [3, 4]]).round(2.6, +1)).toBe(3);
      expect(frange([[1, 2], [3, 4]]).round(2.6, 0)).toBe(3);
    });
    it('should round at the ends of split ranges', function () {
      expect(frange([[1, 2], [3, 4]]).round(0,  0)).toBe(1);
      expect(frange([[1, 2], [3, 4]]).round(0, -1)).toBe(1);
      expect(frange([[1, 2], [3, 4]]).round(0, +1)).toBe(1);
      expect(frange([[1, 2], [3, 4]]).round(5,  0)).toBe(4);
      expect(frange([[1, 2], [3, 4]]).round(5, -1)).toBe(4);
      expect(frange([[1, 2], [3, 4]]).round(5, +1)).toBe(4);
    });
  });
});
