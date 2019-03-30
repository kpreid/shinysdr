// Copyright 2019 Kevin Reid and the ShinySDR contributors
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
  'math',
], (
  import_jasmine,
  import_math
) => {
  const {ji: {
    describe,
    expect,
    it,
  }} = import_jasmine;
  const {
    dB,
    formatFreqExact,
    formatFreqInexactVerbose,
    formatFreqMHz,
    mod,
  } = import_math;
  
  describe('math', () => {
    describe('dB', () => {
      it('should convert decibels to linear', () => {
        expect(dB(-10)).toBeCloseTo(0.1);
        expect(dB(0)).toBe(1);
        expect(dB(3)).toBeCloseTo(2);
        expect(dB(10)).toBe(10);
        expect(dB(20)).toBe(100);
      });
      
      it('should handle exceptional values', () => {
        expect(dB('foo')).toBeNaN();
        expect(dB(NaN)).toBeNaN();
        expect(dB(Infinity)).toBe(Infinity);
        expect(dB(-Infinity)).toBe(0);
      });
    });
    
    // TODO: Negatives
    
    describe('formatFreqExact', () => {
      it('should format', () => {
        // Tests decimal places, edge cases (one prefix to the next), and negative values.
        expect(formatFreqExact(   0)).toBe('0');
        expect(formatFreqExact(  -0)).toBe('0');
        expect(formatFreqExact( 123)).toBe('123');
        expect(formatFreqExact( 123.4)).toBe('123.4');
        expect(formatFreqExact(-123.4)).toBe('-123.4');
        expect(formatFreqExact( 123.456789)).toBe('123.456789');  // no rounding
        expect(formatFreqExact( 999.99999)).toBe('999.99999');
        expect(formatFreqExact(   1.0e3)).toBe('1k');
        expect(formatFreqExact( 123.4e3)).toBe('123.4k');
        expect(formatFreqExact(-999.99999e3)).toBe('-999.99999k');
        expect(formatFreqExact( 999.99999e3)).toBe('999.99999k');
        expect(formatFreqExact(   1.0e6)).toBe('1M');
        expect(formatFreqExact(  -1.0e6)).toBe('-1M');
        expect(formatFreqExact( 123.4e6)).toBe('123.4M');
        expect(formatFreqExact( 999.99999e6)).toBe('999.99999M');
        expect(formatFreqExact(   1.0e9)).toBe('1G');
        expect(formatFreqExact( 123.4e9)).toBe('123.4G');
        expect(formatFreqExact( 123.4e12)).toBe('123400G');
      });
      
      it('should handle exceptional values', () => {
        expect(formatFreqExact('foo')).toBe('NaN');
        expect(formatFreqExact(NaN)).toBe('NaN');
        expect(formatFreqExact(Infinity)).toBe('Infinity');
        expect(formatFreqExact(-Infinity)).toBe('-Infinity');
      });
    });
    
    describe('formatFreqInexactVerbose', () => {
      it('should format', () => {
        // Tests decimal places, edge cases (one prefix to the next), and negative values.
        expect(formatFreqInexactVerbose(   0)).toBe('0.0 Hz');
        expect(formatFreqInexactVerbose(  -0)).toBe('0.0 Hz');
        expect(formatFreqInexactVerbose( 123)).toBe('123.0 Hz');
        expect(formatFreqInexactVerbose( 123.4)).toBe('123.4 Hz');
        expect(formatFreqInexactVerbose(-123.4)).toBe('-123.4 Hz');
        expect(formatFreqInexactVerbose( 123.456789)).toBe('123.457 Hz');  // 3 decimal places
        expect(formatFreqInexactVerbose( 999.99)).toBe('999.99 Hz');
        expect(formatFreqInexactVerbose( 999.99999)).toBe('1000.0 Hz');  // TODO: bug?
        expect(formatFreqInexactVerbose(   1.0e3)).toBe('1.0 kHz');
        expect(formatFreqInexactVerbose( 123.4e3)).toBe('123.4 kHz');
        expect(formatFreqInexactVerbose( 999.99e3)).toBe('999.99 kHz');
        expect(formatFreqInexactVerbose( 999.99999e3)).toBe('1000.0 kHz');  // TODO: bug?
        expect(formatFreqInexactVerbose(-999.99999e3)).toBe('-1000.0 kHz');  // TODO: bug?
        expect(formatFreqInexactVerbose(   1.0e6)).toBe('1.0 MHz');
        expect(formatFreqInexactVerbose( 123.4e6)).toBe('123.4 MHz');
        expect(formatFreqInexactVerbose( 999.99e6)).toBe('999.99 MHz');
        expect(formatFreqInexactVerbose( 999.99999e6)).toBe('1000.0 MHz');  // TODO: bug?
        expect(formatFreqInexactVerbose(   1.0e9)).toBe('1.0 GHz');
        expect(formatFreqInexactVerbose( 123.4e9)).toBe('123.4 GHz');
        expect(formatFreqInexactVerbose( 123.4e12)).toBe('123400.0 GHz');
      });
      
      it('should handle exceptional values', () => {
        expect(formatFreqInexactVerbose('foo')).toBe('NaN Hz');
        expect(formatFreqInexactVerbose(NaN)).toBe('NaN Hz');
        expect(formatFreqInexactVerbose(Infinity)).toBe('Infinity Hz');
        expect(formatFreqInexactVerbose(-Infinity)).toBe('-Infinity Hz');
      });
    });
    
    describe('formatFreqMHz', () => {
      it('should format', () => {
        expect(formatFreqMHz(  0)).toBe('0.00');
        expect(formatFreqMHz(123)).toBe('0.00');
        expect(formatFreqMHz(123.4)).toBe('0.00');
        expect(formatFreqMHz(123.4e3)).toBe('0.12');
        expect(formatFreqMHz(125e3)).toBe('0.13');
        expect(formatFreqMHz(123.4e6)).toBe('123.40');
        expect(formatFreqMHz(123.4e9)).toBe('123400.00');
        expect(formatFreqMHz(123.4e12)).toBe('123400000.00');
      });
      
      it('should handle exceptional values', () => {
        expect(formatFreqMHz('foo')).toBe('NaN');
        expect(formatFreqMHz(NaN)).toBe('NaN');
        expect(formatFreqMHz(Infinity)).toBe('Infinity');
        expect(formatFreqMHz(-Infinity)).toBe('-Infinity');
      });
    });
    
    describe('mod', () => {
      it('should be modulo, not remainder', () => {
        expect(mod(-21, 10)).toBe(9);
        expect(mod(-11, 10)).toBe(9);
        expect(mod(-1, 10)).toBe(9);
        expect(mod(0, 10)).toBe(0);
        expect(mod(1, -10)).toBe(-9);
        expect(mod(1, 10)).toBe(1);
        expect(mod(11, 10)).toBe(1);
        expect(mod(21, 10)).toBe(1);

        expect(mod(1.7, 0.5)).toBeCloseTo(0.2);
        
        expect(mod(1, 0)).toBeNaN();
        expect(mod(1, NaN)).toBeNaN();
        expect(mod(NaN, 10)).toBeNaN();
      });
    });
  });
  
  return 'ok';
});