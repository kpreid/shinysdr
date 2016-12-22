// Copyright 2013, 2014, 2015, 2016, 2017 Kevin Reid <kpreid@switchb.org>
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

// Client-side mirror of shinysdr/types.py

define([], () => {
  'use strict';
  
  const exports = Object.create(null);
  
  class ValueType {
    isSingleValued() {
      // default implementation
      return false;
    }
  }
  exports.ValueType = ValueType;
  
  // Do not instantiate arbitrarily; identity is used.
  class _JSType extends ValueType {
    constructor(jsCoerceFn) {
      super();
      this._jsCoerceFn = jsCoerceFn;
      Object.freeze(this);
    }
  }
  const booleanT = new _JSType(Boolean);
  exports.booleanT = booleanT;
  const numberT = new _JSType(Number);  // TODO: Preserve integer distinction? Not currently useful anywhere.
  exports.numberT = numberT;
  const stringT = new _JSType(String);
  exports.stringT = stringT;
  
  class ConstantT extends ValueType {
    constructor(value) {
      super();
      this.value = value;
      Object.freeze(this);
    }
    
    isSingleValued() { return true; }
  }
  exports.ConstantT = ConstantT;
  
  class EnumT extends ValueType {
    constructor(tableIn) {
      const table = Object.create(null);
      for (var k in tableIn) {
        const row = tableIn[k];
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
      
      super();
      this._table = Object.freeze(table);
      Object.freeze(this);
    }
    
    getTable() {
      return this._table;
    }
    
    isSingleValued() {
      return Object.keys(this._table).length <= 1;
    }
  }
  exports.EnumT = EnumT;

  class RangeT extends ValueType {
    constructor(subranges, logarithmic, integer) {
      super();
      this.mins = Array.prototype.map.call(subranges, function (v) { return v[0]; });
      this.maxes = Array.prototype.map.call(subranges, function (v) { return v[1]; });
      this.logarithmic = logarithmic;
      this.integer = integer;
    }
    
    isSingleValued() {
      return this.mins.length <= 1 && this.maxes.length <= 1 && this.mins[0] === this.maxes[0];
    }
    
    getMin() { return this.mins[0]; }
    getMax() { return this.maxes[this.maxes.length - 1]; }
    
    round(value, direction) {
      // direction is -1, 0, or 1 indicating preferred rounding direction (0 round to nearest)
      value = +value;
      // algorithm is inefficient but adequate
      const length = this.mins.length;
      let bestFit = Infinity;
      let bestIndex = direction === -1 ? 0 : direction === 1 ? length - 1 : undefined;
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
    }
  }
  exports.RangeT = RangeT;

  class NoticeT extends ValueType {
    constructor(alwaysVisible) {
      super();
      this.alwaysVisible = Boolean(alwaysVisible);
      Object.freeze(this);
    }
  }
  exports.NoticeT = NoticeT;

  class TimestampT extends ValueType {
  }
  exports.TimestampT = TimestampT;

  class BulkDataT extends ValueType {
    constructor(info_format, array_format) {
      super();
      // TODO: redesign things so that we have the semantic info from the server
      if (info_format === 'dff' && array_format === 'b') {
        this.dataFormat = 'spectrum-byte';
      } else if (info_format === 'd' && array_format === 'f') {
        this.dataFormat = 'scope-float';
      } else {
        throw new Error('Unexpected bulk data format: ' + info_format + ' ' + array_format);
      }
      Object.freeze(this);
    }
  }
  exports.BulkDataT = BulkDataT;

  const singletonDone = new WeakMap();
  class SingletonValueType extends ValueType {
    constructor() {
      super();
      const c = this.constructor;  // TODO: More ES6ish thing to check?
      if (singletonDone.get(c)) {
        throw new Error('singleton error for ' + c);
      }
      singletonDone.set(c, true);
      Object.freeze(this);
    }
  }

  // type for any value at all
  class AnyT extends SingletonValueType {}
  const anyT = new AnyT();
  exports.anyT = anyT;

  // type for any block
  class BlockT extends SingletonValueType {}
  const blockT = new BlockT();
  exports.blockT = blockT;

  // type for track objects
  class TrackT extends SingletonValueType {}
  const trackT = new TrackT();
  exports.trackT = trackT;

  function typeFromDesc(desc) {
    // TODO if the type is unknown have a warning and fallback instead, or make network.js handle the failure more gracefully
    switch (typeof desc) {
      case 'string':
        switch (desc) {
          case 'reference':
            return blockT;
          case 'boolean':
            return booleanT;
          case 'float64':
            return numberT;
          case 'integer':
            return numberT;
          case 'shinysdr.telemetry.Track':
            return trackT;
          default:
            throw new TypeError('unknown type desc value: ' + desc);
        }
        break;  // satisfy lint (actually unreachable)
      case 'object':
        if (desc === null) {
          return anyT;
        }
        switch (desc.type) {
          case 'ConstantT':
            return new ConstantT(desc.value);
          case 'EnumT':
            return new EnumT(desc.table);
          case 'RangeT':
            return new RangeT(desc.subranges, desc.logarithmic, desc.integer);
          case 'NoticeT':
            return new NoticeT(desc.always_visible);
          case 'TimestampT':
            return new TimestampT();
          case 'BulkDataT':
            return new BulkDataT(desc.info_format, desc.array_format);
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