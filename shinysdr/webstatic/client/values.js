define(['./events'], function (events) {
  'use strict';
  
  var exports = {};
  
  function Enum(valuesIn) {
    var values = Object.create(null);
    for (var k in valuesIn) {
      values[k] = String(valuesIn[k]);
    }
    this.values = Object.freeze(values);
  }
  Enum.prototype.isSingleValued = function () {
    return Object.keys(this.values).length <= 1;
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
    var length = this.mins.length;
    var bestFit = Infinity;
    var bestIndex = direction == -1 ? 0 : direction == 1 ? length - 1 : undefined;
    for (var i = 0; i < length; i++) {
      var min = this.mins[i];
      var max = this.maxes[i];
      var fit;
      var upwardFit = value > max ? Infinity : min - value;
      var downwardFit = value < min ? Infinity : value - max;
      switch (direction) {
        case 0: fit = Math.min(upwardFit, downwardFit); break;
        case 1: fit = upwardFit; break;
        case -1: fit = downwardFit; break;
        default: throw new Error('bad rounding direction'); break;
      }
      //console.log('fit for ', min, max, ' is ', fit);
      if (fit < bestFit) {
        bestFit = fit;
        bestIndex = i;
      }
    }
    if (bestIndex === undefined) throw new Error("can't happen");
    min = this.mins[bestIndex];
    max = this.maxes[bestIndex];
    //console.log(value, direction, min, max);
    if (value < min) value = min;
    if (value > max) value = max;
    return value;
  };
  exports.Range = Range;

  var any = Object.freeze({});
  exports.any = any;

  function typeFromDesc(desc) {
    switch (typeof desc) {
      case 'string':
        switch (desc) {
          case 'boolean':
            return Boolean; // will do till we need something fancier
        }
      case 'object':
        if (desc === null) {
          return any;
        }
        switch (desc.type) {
          case 'enum':
            return new Enum(desc.values);
          case 'range':
            return new Range(desc.subranges, desc.logarithmic, desc.integer);
          default:
            throw new TypeError('unknown type desc tag: ' + desc.type);
        }
      default:
        throw new TypeError('unknown type desc value: ' + desc);
    }
  }
  exports.typeFromDesc = typeFromDesc;
  
  function Cell(type) {
    if (type === undefined) { throw new Error('oops type: ' + this.constructor.name); }
    this.type = type;
    this.n = new events.Notifier();
  }
  Cell.prototype.depend = function(listener) {
    this.n.listen(listener);
    return this.get();
  };
  exports.Cell = Cell;
  
  function LocalCell(type) {
    Cell.call(this, type);
    this._value = undefined;
  }
  LocalCell.prototype = Object.create(Cell.prototype, {constructor: {value: LocalCell}});
  LocalCell.prototype.get = function() {
    return this._value;
  };
  LocalCell.prototype.set = function(v) {
    this._value = v;
    this.n.notify();
  };
  exports.LocalCell = LocalCell;
  
  // Adds a prefix to localStorage keys
  function StorageNamespace(base, prefix) {
    this._base = base;
    this._prefix = prefix;
  }
  StorageNamespace.prototype.getItem = function (key) {
    return this._base.getItem(this._prefix + key);
  };
  StorageNamespace.prototype.setItem = function (key, value) {
    return this._base.setItem(this._prefix + key, value);
  };
  StorageNamespace.prototype.removeItem = function (key) {
    return this._base.removeItem(this._prefix + key);
  };
  exports.StorageNamespace = StorageNamespace;
  
  return Object.freeze(exports);
});