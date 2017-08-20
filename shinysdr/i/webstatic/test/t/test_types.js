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

define([
  '/test/jasmine-glue.js',
  'types',
], (
  import_jasmine,
  types
) => {
  const {ji: {
    describe,
    expect,
    it,
  }} = import_jasmine;
  const {
    typeFromDesc,
  } = types;
  
  describe('types', () => {
    function singletonTypeTest(identifier, serialization) {
      describe(identifier, () => {
        it('should exist and have the correct toString', () =>  {
          expect(types[identifier].toString()).toBe(identifier);
        });
        
        it('should be deserializable', () => {
          expect(typeFromDesc(serialization)).toBe(types[identifier]);
        });
      });
    }
    singletonTypeTest('booleanT', 'boolean');
    singletonTypeTest('numberT', 'float64');
    singletonTypeTest('stringT', 'string');
    singletonTypeTest('anyT', null);
    singletonTypeTest('blockT', 'reference');
    singletonTypeTest('trackT', 'shinysdr.telemetry.Track');
    
    describe('EnumT', () => {
      const EnumT = types.EnumT;
    
      it('should have the correct toString', () => {
        expect(new EnumT({'a': 'aa'}).toString()).toBe('EnumT("a")');
      });
    
      it('should be deserializable', () => {
        expect(typeFromDesc({'type': 'EnumT'})).toMatch(/^EnumT\(/);
        // TODO show that table made it through
      });
    
      it('reports isSingleValued correctly', () => {
        expect(new EnumT({'a': 'aa', 'b': 'bb'}).isSingleValued()).toBe(false);
        expect(new EnumT({'a': 'aa'}).isSingleValued()).toBe(true);
      });
    
      it('preserves metadata', () => {
        expect(new EnumT({'a': {
          'label': 'b',
          'description': 'c',
          'sort_key': 'd'
        }}).getEnumTable().get('a')).toEqual({
          'label': 'b',
          'description': 'c',
          'sort_key': 'd'
        });
      });
    
      it('expands metadata', () => {
        expect(new EnumT({'a': 'b'}).getEnumTable().get('a')).toEqual({
          'label': 'b',
          'description': null,
          'sort_key': 'a'
        });
      });
    });
  
    describe('RangeT', () => {
      const RangeT = types.RangeT;
      
      function frange(subranges) {
        return new RangeT(subranges, false, false);
      }
    
      it('should have the correct toString', () => {
        expect(frange([[0, 100]]).toString()).toBe('RangeT(lin real [0, 100])');
      });
      
      it('should round at the ends of simple ranges', () => {
        expect(frange([[1, 3]]).round(0, -1)).toBe(1);
        expect(frange([[1, 3]]).round(2, -1)).toBe(2);
        expect(frange([[1, 3]]).round(4, -1)).toBe(3);
        expect(frange([[1, 3]]).round(0, 1)).toBe(1);
        expect(frange([[1, 3]]).round(2, 1)).toBe(2);
        expect(frange([[1, 3]]).round(4, 1)).toBe(3);
      });
      it('should round in the gaps of split ranges', () => {
        expect(frange([[1, 2], [3, 4]]).round(2.4, 0)).toBe(2);
        expect(frange([[1, 2], [3, 4]]).round(2.4, -1)).toBe(2);
        expect(frange([[1, 2], [3, 4]]).round(2.4, +1)).toBe(3);
        expect(frange([[1, 2], [3, 4]]).round(2.6, -1)).toBe(2);
        expect(frange([[1, 2], [3, 4]]).round(2.6, +1)).toBe(3);
        expect(frange([[1, 2], [3, 4]]).round(2.6, 0)).toBe(3);
      });
      it('should round at the ends of split ranges', () => {
        expect(frange([[1, 2], [3, 4]]).round(0,  0)).toBe(1);
        expect(frange([[1, 2], [3, 4]]).round(0, -1)).toBe(1);
        expect(frange([[1, 2], [3, 4]]).round(0, +1)).toBe(1);
        expect(frange([[1, 2], [3, 4]]).round(5,  0)).toBe(4);
        expect(frange([[1, 2], [3, 4]]).round(5, -1)).toBe(4);
        expect(frange([[1, 2], [3, 4]]).round(5, +1)).toBe(4);
      });
      it('should produce an enumTable', () => {
        expect(Array.from(frange([[1, 2], [3, 4]]).getEnumTable().keys())).toEqual([1, 2, 3, 4]);
      });
    });
    
    describe('typeFromDesc', () => {
      // TODO: test handling of weird values
    });
    
  });
  
  return 'ok';
});