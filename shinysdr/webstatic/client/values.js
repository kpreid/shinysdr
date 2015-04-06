// Copyright 2013, 2014 Kevin Reid <kpreid@switchb.org>
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

  function Notice(alwaysVisible) {
    this.alwaysVisible = alwaysVisible;
  }
  exports.Notice = Notice;

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
          case 'notice':
            return new Notice(desc.always_visible);
          case 'bulk_data':
            return new BulkDataType(desc.info_format, desc.array_format);
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
  
  function identical(a, b) {
    if (typeof a === 'number' && typeof b === 'number') {
      return (
        (a === b && 1/a === 1/b)  // finite, zero, or infinity
        || (isNaN(a) && isNaN(b))  // NaN
      );
    } else {
      return a === b;
    }
  }
  
  // Cell whose state is not persistent
  function LocalCell(type, initialValue) {
    Cell.call(this, type);
    this._value = initialValue;
  }
  LocalCell.prototype = Object.create(Cell.prototype, {constructor: {value: LocalCell}});
  LocalCell.prototype.get = function() {
    return this._value;
  };
  LocalCell.prototype.set = function(v) {
    if (!identical(this._value, v)) {
      this._value = v;
      this.n.notify();
    }
  };
  exports.LocalCell = LocalCell;
  
  // Cell whose state is not settable
  function LocalReadCell(type, initialValue) {
    Cell.call(this, type);
    this._value = initialValue;
    // TODO use facets instead
    this._update = function(v) {
      if (this._value !== v) {
        this._value = v;
        this.n.notify();
      }
    }.bind(this);
  }
  LocalReadCell.prototype = Object.create(Cell.prototype, {constructor: {value: LocalReadCell}});
  LocalReadCell.prototype.get = function() {
    return this._value;
  };
  exports.LocalReadCell = LocalReadCell;
  
  // Cell which cannot be set
  function ConstantCell(type, value) {
    Cell.call(this, type);
    this._value = value;
    this.n = new events.Neverfier();  // TODO throwing away initial value, unclean
  }
  ConstantCell.prototype = Object.create(Cell.prototype, {constructor: {value: ConstantCell}});
  ConstantCell.prototype.get = function () {
    return this._value;
  };
  exports.ConstantCell = ConstantCell;
  
  function DerivedCell(type, scheduler, compute) {
    Cell.call(this, type);
    
    this._compute = compute;
    this._needsCompute = false;
    
    var dirtyCallback = this._dirty = function derivedCellDirtyCallback() {
      this.n.notify();
    }.bind(this);
    var cell = this;
    this._dirty.scheduler = {
      // This scheduler-like object is a kludge so that we can get a prompt dirty flag.
      // I suspect that there are other use cases for this, in which case it should be extracted into a full scheduler implementation (or a part of the base Scheduler) but I'm waiting to see what the other cases look like first.
      toString: function () { return '[DerivedCell gimmick scheduler]'; },
      enqueue: function (f) {
        if (f !== dirtyCallback) {
          throw new Error('f !== dirtyCallback');
        }
        if (!cell._needsCompute) {
          cell._needsCompute = true;
          cell.n.notify();
        }
      }
    };
    
    // Register initial notifications by computing once.
    // Note: this would not be necessary if .depend() were the only interface instead of .n.listen(), so it is perhaps worth considering that.
    this._value = (1,this._compute)(this._dirty);
  }
  DerivedCell.prototype = Object.create(Cell.prototype, {constructor: {value: DerivedCell}});
  DerivedCell.prototype.get = function () {
    if (this._needsCompute) {
      // Note that this._compute could throw. The behavior we have chosen here is to throw on every get call. Other possible behaviors would be to catch and log (or throw-async) the exception and return either a stale value or a pumpkin value.
      this._value = (1,this._compute)(this._dirty);
      this._needsCompute = false;
    }
    return this._value;
  }
  exports.DerivedCell = DerivedCell;
  
  // Adds a prefix to Storage (localStorage) keys
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
  
  var allStorageCellNotifiers = [];
  // Note that browsers do not fire this event unless the storage was changed from SOME OTHER window; so this code is not usually applicable. We're also being imprecise.
  window.addEventListener('storage', function (event) {
    allStorageCellNotifiers.forEach(function (n) { n.notify(); });
  });
  
  // Presents a Storage (localStorage) entry as a cell
  // Warning: Only one cell should exist per unique key, or notifications may not occur; also, creating cells repeatedly will leak.
  // TODO: Fix that by interning cells.
  function StorageCell(storage, type, key) {
    key = String(key);

    Cell.call(this, type);

    this._storage = storage;
    this._key = key;

    allStorageCellNotifiers.push(this.n);
  }
  StorageCell.prototype = Object.create(Cell.prototype, {constructor: {value: StorageCell}});
  StorageCell.prototype.get = function() {
    return JSON.parse(this._storage.getItem(this._key));
  };
  StorageCell.prototype.set = function(value) {
    this._storage.setItem(this._key, JSON.stringify(value));
    this.n.notify();
  };
  exports.StorageCell = StorageCell;
  
  function getInterfaces(object) {
    var result = [];
    // TODO kludgy, need better representation of interfaces
    Object.getOwnPropertyNames(object).forEach(function (key) {
      var match = /^_implements_(.*)$/.exec(key);
      if (match) {
        result.push(match[1]);
      }
    });
    return result;
  }
  exports.getInterfaces = getInterfaces;
  
  function isImplementing(object, interfaceName) {
    return !!object['_implements_' + interfaceName];
  }
  exports.getInterfaces = getInterfaces;
  
  function cellProp(scheduler, cell, prop) {
    // TODO: technically need a block-or-undefined type
    return new DerivedCell(block, scheduler, function (dirty) {
      var object = cell.depend(dirty);
      if (object === undefined) {
        return;
      }
      if (typeof object !== 'object') {
        throw new Error('cellProp input neither an object nor undefined');
      }
      object._reshapeNotice.listen(dirty);
      var propCell = object[prop];
      if (propCell === undefined || propCell.type !== block) {
        return undefined;
      }
      return propCell.depend(dirty);
    });
  }
  
  // Maintain an index of objects, by interface name, in a tree
  function Index(scheduler, rootCell) {
    var cells = [];
    var objectsByInterface = Object.create(null);
    
    function gobi(interfaceName) {
      return (objectsByInterface[interfaceName] ||
        (objectsByInterface[interfaceName] =
          new LocalReadCell(any, Object.freeze([]))));
    }
    
    function flush(interfaceName) {
      var objectsCell = gobi(interfaceName);
      var old = objectsCell.get();
      var nu = old.filter(function (cell) {
        var object = cell.get();
        return object !== undefined && isImplementing(object, interfaceName);
      });
      if (nu.length < old.length) {
        objectsCell._update(Object.freeze(nu));
      }
    }
    
    function insert(cell) {
      if (cells.indexOf(cell) !== -1) {
        return;
      }
      if (cell.type !== block) {
        return;
      }
      
      var i = cells.length;
      cells.push(cell);
      
      var propCells = Object.create(null);
      var interfaces = [];
      
      function update() {
        var object = cell.depend(update);
        
        interfaces.forEach(flush);
        if (typeof object !== 'object') {  // if e.g. no longer existant
          return;
        }
        
        var nu = getInterfaces(object);
        
        nu.forEach(function (interfaceName) {
          var objectsCell = gobi(interfaceName);
          var existingObjects = objectsCell.get();
          if (existingObjects.indexOf(cell) < 0) {
            // TODO: fix O(n^2) behavior
            objectsCell._update(Object.freeze(existingObjects.concat([cell])));
          }
        });
        
        // remember which interfaces' object lists to flush when this cell changes in case it no longer implements the interfaces. TODO: Take a delta to minimize work
        interfaces = nu;
        
        // Add all cells found in this object
        for (var key in object) {
          var childCell = object[key];
          if (!(childCell !== null && typeof childCell == 'object' && 'get' in childCell)) {
            console.error('Unexpected non-cell', childCell, 'in', object);
            continue;
          }
          
          // memoized
          if (!propCells[key]) {
            insert(propCells[key] = cellProp(scheduler, cell, key));
          }
        }
        if ('_reshapeNotice' in object) {  // TODO mandatory
          object._reshapeNotice.listen(update);
        }
      }
      update.scheduler = scheduler;
      
      update();
    }
    
    insert(rootCell);
    
    this.implementing = function (interfaceName) {
      var cellsCell = gobi(interfaceName);
      return new DerivedCell(any, scheduler, function (dirty) {
        return cellsCell.depend(dirty).map(function (cell) {
          return cell.depend(dirty);
        }).filter(function (block) {
          // filter out stale propcells that didn't happen to be removed in the right order. or something. TODO see if the need for this is actually a bug.
          return !!block;
        });
      });
    };
  }
  exports.Index = Index;
  
  // make an object which is like a remote object (called block for legacy reasons)
  function makeBlock(obj) {
    Object.defineProperty(obj, '_reshapeNotice', {value: new events.Neverfier()});
    return obj;
  }
  exports.makeBlock = makeBlock;
  
  return Object.freeze(exports);
});