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

'use strict';

define(['./events', './types'], function (events, types) {
  const {
    Neverfier,
    Notifier
  } = events;
  const {
    anyT,
    booleanT,
    blockT,
    numberT,
    stringT,
    ValueType,
  } = types;
  
  const exports = Object.create(null);

  function Cell(type_or_metadata) {
    let type;
    let metadata;
    if (type_or_metadata === undefined) {
      throw new Error('Cell constructed without metadata: ' + this.constructor.name);
    } else if (type_or_metadata.value_type && type_or_metadata.naming) {
      type = type_or_metadata.value_type;
      metadata = type_or_metadata;
    } else {
      type = type_or_metadata;
      metadata = {
        value_type: type_or_metadata,
        naming: {
            'type': 'EnumRow',
            'label': null,
            'description': null,
            'sort_key': null
        }
      };
    }
    if (!(type instanceof ValueType)) {
      throw new TypeError('cell type not a ValueType: ' + type);
    }
    // TODO: .metadata was added after .type, and .type is now redundant. Look at whether we want to remove it -- probably not.
    this.type = type;
    this.metadata = metadata;
    this.n = new Notifier();
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
  function LocalCell(type_or_metadata, initialValue) {
    Cell.call(this, type_or_metadata);
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
  function LocalReadCell(type_or_metadata, initialValue) {
    Cell.call(this, type_or_metadata);
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
  const IMPLICIT_TYPE_PUMPKIN = {};
  function ConstantCell(value, type_or_metadata=IMPLICIT_TYPE_PUMPKIN) {
    if (type_or_metadata == IMPLICIT_TYPE_PUMPKIN) {
      switch (typeof value) {
        case 'boolean': type_or_metadata = booleanT; break;
        case 'number': type_or_metadata = numberT; break;
        case 'string': type_or_metadata = stringT; break;
        case 'object':
          if (value !== null && value._reshapeNotice) {
            type_or_metadata = blockT;
            break;
          }
          throw new Error('ConstantCell: type inference for object ' + JSON.stringify(value) + ' not supported');
        default:
          throw new Error('ConstantCell: type inference for value of type ' + (typeof value) + ' not supported');
      }
    }
    
    Cell.call(this, type_or_metadata);
    this._value = value;
    this.n = new Neverfier();  // TODO throwing away super's value, unclean
  }
  ConstantCell.prototype = Object.create(Cell.prototype, {constructor: {value: ConstantCell}});
  ConstantCell.prototype.get = function () {
    return this._value;
  };
  exports.ConstantCell = ConstantCell;
  
  function DerivedCell(type_or_metadata, scheduler, compute) {
    Cell.call(this, type_or_metadata);
    
    const dirtyCallback = function derivedCellDirtyCallback() {
      this.n.notify();
    }.bind(this);
    var cell = this;
    dirtyCallback.scheduler = {
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
    
    this._compute = Function.prototype.bind.call(compute, undefined, dirtyCallback);
    this._needsCompute = true;
    
    // Register initial notifications by computing once.
    // Note: this would not be necessary if .depend() were the only interface instead of .n.listen(), so it is perhaps worth considering that.
    this.get();
  }
  DerivedCell.prototype = Object.create(Cell.prototype, {constructor: {value: DerivedCell}});
  DerivedCell.prototype.get = function () {
    if (this._needsCompute) {
      // Note that this._compute could throw. The behavior we have chosen here is to throw on every get call. Other possible behaviors would be to catch and log (or throw-async) the exception and return either a stale value or a pumpkin value.
      this._value = this._compute();
      this._needsCompute = false;
    }
    return this._value;
  };
  exports.DerivedCell = DerivedCell;
  
  // Cell which does not really hold a value, but 
  function CommandCell(fn, type_or_metadata) {
    // TODO: type is kind of useless, make it useful or make it explicitly stubbed out
    Cell.call(this, type_or_metadata);
    this.n = new Neverfier();  // TODO throwing away super's value, unclean
    this.invoke = function commandProxy(callback) {
      if (!callback) {
        callback = Function.prototype;
      } else if (typeof callback !== 'function') {
        // sanity check
        throw new Error('passed a non-function to CommandCell.invoke');
      }
      fn(callback);
    };
  }
  CommandCell.prototype = Object.create(Cell.prototype, {constructor: {value: CommandCell}});
  CommandCell.prototype.get = function () {
    return null;
  };
  exports.CommandCell = CommandCell;
  
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
  
  var allStorageCells = [];
  // Note that browsers do not fire this event unless the storage was changed from SOME OTHER window; so this code is not usually applicable.
  // TODO: Use the properties of the storage event to not need to iterate over all cells. This will require StorageNamespace to provide remapped events.
  window.addEventListener('storage', function (event) {
    allStorageCells.forEach(function (cell) { cell.get(); });
  });
  
  // Presents a Storage (localStorage) entry as a cell; the value must be representable as JSON.
  // Warning: Only one cell should exist per unique key, or notifications may not occur; also, creating cells repeatedly will leak.
  // TODO: Fix that by interning cells.
  function StorageCell(storage, type_or_metadata, initialValue, key) {
    key = String(key);

    Cell.call(this, type_or_metadata);

    this._storage = storage;
    this._key = key;
    this._initialValue = JSON.parse(JSON.stringify(initialValue));
    
    this._lastSeenString = {};  // guaranteed unequal
    this._lastSeenValue = undefined;
    this.get();  // initialize last-seen
    
    allStorageCells.push(this);
  }
  StorageCell.prototype = Object.create(Cell.prototype, {constructor: {value: StorageCell}});
  StorageCell.prototype.get = function() {
    var storedString = this._storage.getItem(this._key);
    
    if (storedString !== this._lastSeenString) {
      // (Possibly unexpected) change.
      this._lastSeenString = storedString;
      this.n.notify();
    } else {
      // Shortcut: don't parse.
      return this._lastSeenValue;
    }
    
    let value = this._initialValue;
    if (storedString) {
      try {
        value = JSON.parse(storedString);
      } catch (e) {
        if (e instanceof SyntaxError) {
          console.warn('Malformed JSON found in Storage (ignored): ' + JSON.stringify(storedString));
        } else {
          throw e;
        }
      }
    }
    this._lastSeenValue = value;
    return value;
  };
  StorageCell.prototype.set = function(value) {
    this._storage.setItem(this._key, JSON.stringify(value));
    this.get();  // trigger notification and read-back
  };
  exports.StorageCell = StorageCell;
  
  // Adapt Promises to the cell.depend() style protocol.
  const dependOnPromiseTable = new WeakMap();
  function dependOnPromise(callback, placeholderValue, promise) {
    // Promise value lookup is also keyed on the scheduler to minimize the degree to which we're adding global state to the system; this is analogous to how whether a given callback is scheduled is also per-scheduler.
    const scheduler = callback.scheduler;
    if (!dependOnPromiseTable.has(scheduler)) {
      dependOnPromiseTable.set(scheduler, new WeakMap());
    }
    const syncPromiseValues = dependOnPromiseTable.get(scheduler);
    
    if (syncPromiseValues.has(promise)) {
      return syncPromiseValues.get(promise);
    } else {
      promise.then(value => {
        syncPromiseValues.set(promise, value);
        scheduler.enqueue(callback);
      });
      return placeholderValue;
    }
  }
  exports.dependOnPromise = dependOnPromise;
  
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
  
  // Creates a cell whose value is cell.get()[prop].get() if that expression is valid and undefined otherwise.
  // TODO: Write tests of this because it is hairy.
  function cellPropOfBlockCell(scheduler, cell, prop, restrictToBlock) {
    // TODO: technically need a blockT-or-undefined type
    return new DerivedCell(restrictToBlock ? blockT : anyT, scheduler, function (dirty) {
      const object = cell.depend(dirty);
      if (object === undefined) {
        return;
      }
      if (typeof object !== 'object') {
        throw new Error('cellProp input neither an object nor undefined');
      }
      object._reshapeNotice.listen(dirty);
      const propCell = object[prop];
      if (!(propCell !== undefined && (!restrictToBlock || propCell.type === blockT))) {
        return undefined;
      }
      return propCell.depend(dirty);
    });
  }
  exports.cellPropOfBlockCell = cellPropOfBlockCell;
  
  function cellPropOfBlock(scheduler, obj, prop, restrictToBlock) {
    return cellPropOfBlockCell(scheduler, new ConstantCell(obj, blockT), prop, restrictToBlock);
  }
  exports.cellPropOfBlock = cellPropOfBlock;
  
  // Maintain an index of objects, by interface name, in a tree
  function Index(scheduler, rootCell) {
    var cells = [];
    var objectsByInterface = Object.create(null);
    
    function gobi(interfaceName) {
      return (objectsByInterface[interfaceName] ||
        (objectsByInterface[interfaceName] =
          new LocalReadCell(anyT, Object.freeze([]))));
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
      if (cell.type !== blockT) {
        return;
      }
      
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
          // TODO: centralize this is-a-cell test and any others like it
          if (!(childCell !== null && typeof childCell === 'object' && 'get' in childCell)) {
            if (typeof childCell === 'function') {
              // allow methods. TODO revisit what the contract of a blockT is
              continue;
            }
            console.error('Unexpected non-cell', childCell, 'in', object);
            continue;
          }
          
          // memoized
          if (!propCells[key]) {
            insert(propCells[key] = cellPropOfBlockCell(scheduler, cell, key, true));
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
      const cellsCell = gobi(interfaceName);
      return new DerivedCell(anyT, scheduler, function (dirty) {
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
  
  // Turn the provided object into one which is like a remote object (called blockT for legacy reasons) and return it.
  function makeBlock(obj) {
    Object.defineProperty(obj, '_reshapeNotice', {value: new Neverfier()});
    return obj;
  }
  exports.makeBlock = makeBlock;
  
  return Object.freeze(exports);
});