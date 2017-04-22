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

define(function () {
  'use strict';
  
  var exports = {};
  
  // true modulo, not %
  function mod(value, modulus) {
    return (value % modulus + modulus) % modulus;
  }
  exports.mod = mod;
  
  // Convert dB to factor.
  function dB(x) {
    return Math.pow(10, 0.1 * x);
  }
  exports.dB = dB;
  
  function formatFreqMHz(freq) {
    return (freq / 1e6).toFixed(2);
  }
  exports.formatFreqMHz = formatFreqMHz;

  // "exact" as in doesn't drop digits. Used in frequency scale.
  function formatFreqExact(freq) {
    freq = +freq;
    var a = Math.abs(freq);
    if (a < 1e3) {
      return String(freq);
    } else if (a < 1e6) {
      return freq / 1e3 + 'k';
    } else if (a < 1e9) {
      return freq / 1e6 + 'M';
    } else {
      return freq / 1e9 + 'G';
    }
  }
  exports.formatFreqExact = formatFreqExact;

  // Format with dropping digits likely not cared about, and units. Used in receiver frequency marks.
  function formatFreqInexactVerbose(freq) {
    freq = +freq;
    var a = Math.abs(freq);
    var prefix;
    if (a < 1e3) {
      prefix = '';
    } else if (a < 1e6) {
      freq /= 1e3;
      prefix = 'k';
    } else if (a < 1e9) {
      freq /= 1e6;
      prefix = 'M';
    } else {
      freq /= 1e9;
      prefix = 'G';
    }
    var freqText = freq.toFixed(3);
    // toFixed rounds, but also adds zeros; we want only the rounding.
    freqText = freqText.replace(/([0-9])0+$/, '$1');
    return freqText + ' ' + prefix + 'Hz';
  }
  exports.formatFreqInexactVerbose = formatFreqInexactVerbose;
  
  return Object.freeze(exports);
});

