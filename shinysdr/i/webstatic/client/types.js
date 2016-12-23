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

define([], () => {
  'use strict';
  
  var exports = Object.create(null);
  
  function isSingleValued(type) {
    // TODO: Stop using Boolean etc. as type objects and remove the need for this feature test
    return type.isSingleValued && type.isSingleValued();
  }
  exports.isSingleValued = isSingleValued;
  
  function Constant(value) {
    this.value = value;
  }
  Constant.prototype.isSingleValued = function () {
    return true;
  };
  exports.Constant = Constant;
  
  function Enum(tableIn) {
    var table = Object.create(null);
    for (var k in tableIn) {
      var row = tableIn[k];
      switch (typeof row) {
        case 'string':
          table[k] = {
            label: row,
            description: null,
            sort_key: k
          };
          break;
        case 'object':
          table[k] = row;
          break;
        default:
          throw new TypeError('enum row not string or EnumRow: ' + row);
      }
    }
    this._table = Object.freeze(table);
    Object.freeze(this);
  }
  Enum.prototype.getTable = function () {
    return this._table;
  };
  Enum.prototype.isSingleValued = function () {
    return Object.keys(this._table).length <= 1;
  };
  exports.Enum = Enum;

  function Range(subranges, logarithmic, integer) {
    this.mins = Array.prototype.map.call(subranges, function (v) { return v[0]; });
    this.maxes = Array.prototype.map.call(subranges, function (v) { return v[1]; });
    this.logarithmic = logarithmic;
    this.integer = integer;
  }
  Range.prototype.isSingleValued = function () {
    return this.mins.length <= 1 && this.maxes.length <= 1 && this.mins[0] === this.maxes[0];
  };
  Range.prototype.getMin = function() {
    return this.mins[0];
  };
  Range.prototype.getMax = function() {
    return this.maxes[this.maxes.length - 1];
  };
  Range.prototype.round = function(value, direction) {
    // direction is -1, 0, or 1 indicating preferred rounding direction (0 round to nearest)
    value = +value;
    // algorithm is inefficient but adequate
    const length = this.mins.length;
    let bestFit = Infinity;
    let bestIndex = direction == -1 ? 0 : direction == 1 ? length - 1 : undefined;
    for (let i = 0; i < length; i++) {
      const min = this.mins[i];
      const max = this.maxes[i];
      const upwardFit = value > max ? Infinity : min - value;
      const downwardFit = value < min ? Infinity : value - max;
      let fit;
      switch (direction) {
        case 0: fit = Math.min(upwardFit, downwardFit); break;
        case 1: fit = upwardFit; break;
        case -1: fit = downwardFit; break;
        default: throw new Error('bad rounding direction');
      }
      //console.log('fit for ', min, max, ' is ', fit);
      if (fit < bestFit) {
        bestFit = fit;
        bestIndex = i;
      }
    }
    if (bestIndex === undefined) throw new Error("can't happen");
    const min = this.mins[bestIndex];
    const max = this.maxes[bestIndex];
    //console.log(value, direction, min, max);
    if (value < min) value = min;
    if (value > max) value = max;
    return value;
  };
  exports.Range = Range;

  // TODO: probably ought to have these type-_constructor_ names be named in some systematic way that distinguishes them from value-constructors.

  function Notice(alwaysVisible) {
    this.alwaysVisible = alwaysVisible;
  }
  exports.Notice = Notice;

  function Timestamp() {
  }
  exports.Timestamp = Timestamp;

  function BulkDataType(info_format, array_format) {
    // TODO: redesign things so that we have the semantic info from the server
    if (info_format == 'dff' && array_format == 'b') {
      this.dataFormat = 'spectrum-byte';
    } else if (info_format == 'd' && array_format == 'f') {
      this.dataFormat = 'scope-float';
    } else {
      throw new Error('Unexpected bulk data format: ' + info_format + ' ' + array_format);
    }
  }
  exports.BulkDataType = BulkDataType;

  // type for any block
  var block = Object.freeze({});
  exports.block = block;

  var any = Object.freeze({});
  exports.any = any;

  // type for track objects
  // TODO type name capitalization is getting inconsistent.
  var Track = Object.freeze({});
  exports.Track = Track;

  function typeFromDesc(desc) {
    // TODO if the type is unknown have a warning and fallback instead, or make network.js handle the failure more gracefully
    switch (typeof desc) {
      case 'string':
        switch (desc) {
          case 'block':
            return block;
          case 'boolean':
            return Boolean; // will do till we need something fancier
          case 'float64':
            return Number;
          case 'integer':
            return Number;
          case 'shinysdr.telemetry.Track':
            return Track;
          default:
            throw new TypeError('unknown type desc value: ' + desc);
        }
        break;  // satisfy lint (actually unreachable)
      case 'object':
        if (desc === null) {
          return any;
        }
        switch (desc.type) {
          case 'constant':
            return new Constant(desc.value);
          case 'enum':
            return new Enum(desc.table);
          case 'range':
            return new Range(desc.subranges, desc.logarithmic, desc.integer);
          case 'notice':
            return new Notice(desc.always_visible);
          case 'Timestamp':
            return new Timestamp();
          case 'bulk_data':
            return new BulkDataType(desc.info_format, desc.array_format);
          default:
            throw new TypeError('unknown type desc tag: ' + desc.type);
        }
        break;  // satisfy lint (actually unreachable)
      default:
        throw new TypeError('unknown type desc value: ' + desc);
    }
  }
  exports.typeFromDesc = typeFromDesc;
  
  return Object.freeze(exports);
});