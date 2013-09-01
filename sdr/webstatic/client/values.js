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
  exports.Enum = Enum;

  function Range(min, max, logarithmic, integer) {
    this.min = min;
    this.max = max;
    this.logarithmic = logarithmic;
    this.integer = integer;
  }
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
            return new Range(desc.min, desc.max, desc.logarithmic, desc.integer);
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