// Copyright 2013, 2014, 2015, 2016 Kevin Reid <kpreid@switchb.org>
// 
// This file is part of ShinySDR.
// 
// ShinySDR is free software: you can redistribute it and/or modify
// it under the terms of the GNU General Public License as published by
// the Free Software Foundation, either version 3 of the License, or
// (at your option) any later version.
// 
// ShinySDR is distributed in the hope that it will be useful,
// but WITHOUT ANY WARRANTY; without even the implied warranty of
// MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
// GNU General Public License for more details.
// 
// You should have received a copy of the GNU General Public License
// along with ShinySDR.  If not, see <http://www.gnu.org/licenses/>.

'use strict';

describe('types', function () {
  var types = shinysdr.types;
  
  describe('Enum', function () {
    var Enum = types.Enum;
    
    it('reports isSingleValued correctly', function () {
      expect(new Enum({'a': 'aa', 'b': 'bb'}).isSingleValued()).toBe(false);
      expect(new Enum({'a': 'aa'}).isSingleValued()).toBe(true);
    });
    
    it('preserves metadata', function () {
      expect(new Enum({'a': {
        'label': 'b',
        'description': 'c',
        'sort_key': 'd'
      }}).getTable()['a']).toEqual({
        'label': 'b',
        'description': 'c',
        'sort_key': 'd'
      });
    });
    
    it('expands metadata', function () {
      expect(new Enum({'a': 'b'}).getTable()['a']).toEqual({
        'label': 'b',
        'description': null,
        'sort_key': 'a'
      });
    });
  });
  
  describe('Range', function () {
    var Range = types.Range;
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

testScriptFinished();
