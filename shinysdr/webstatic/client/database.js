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

define(['./events', './network', './values'], function (events, network, values) {
  'use strict';
  
  var AddKeepDrop = events.AddKeepDrop;
  var DerivedCell = values.DerivedCell;
  var Neverfier = events.Neverfier;
  var Notifier = events.Notifier;
  var StorageCell = values.StorageCell;
  var any = values.any;
  var externalGet = network.externalGet;
  var statusCategory = network.statusCategory;
  var xhrpost = network.xhrpost;
  
  var exports = {};
  
  function Source() {
    
  }
  Source.prototype.getAll = function () {
    throw new Error('getAll not overridden!');
  };
  Source.prototype.getGeneration = function () {
    throw new Error('getGeneration not overridden!');
  };
  Source.prototype._isUpToDate = function () {
    throw new Error('_isUpToDate not overridden!');
  };
  Source.prototype.first = function () {
    return this.getAll()[0];
  };
  Source.prototype.last = function () {
    var entries = this.getAll();
    return entries[entries.length - 1];
  };
  Source.prototype.inBand = function (lower, upper) {
    return new FilterView(this, function inBandFilter(record) {
      return record.upperFreq >= lower &&
             record.lowerFreq <= upper;
    });
  };
  Source.prototype.type = function (type) {
    return new FilterView(this, function typeFilter(record) {
      return record.type === type;
    });
  };
  Source.prototype.string = function (str) {
    var re = new RegExp(str, 'i');
    return new FilterView(this, function stringFilter(record) {
      return re.test(record.label) || re.test(record.notes);
    });
  };
  Source.prototype.groupSameFreq = function () {
    return new GroupView(this);
  };
  Source.prototype.forEach = function (f) {
    this.getAll().forEach(f);
  };
  
  function View(db, filter) {
    this._viewGeneration = NaN;
    this._entries = [];
    this._db = db;
    this.n = this._db.n;
  }
  View.prototype = Object.create(Source.prototype, {constructor: {value: View}});
  View.prototype._isUpToDate = function () {
    return this._viewGeneration === this._db.getGeneration() && this._db._isUpToDate();
  };
  View.prototype.getAll = function () {
    var entries;
    if (!this._isUpToDate()) {
      this._entries = Object.freeze(this._execute(this._db.getAll()));
      this._viewGeneration = this._db.getGeneration();
    }
    return this._entries;
  };
  View.prototype.getGeneration = function () {
    return this._viewGeneration;
  };
  
  function FilterView(db, filter) {
    View.call(this, db);
    this._filter = filter;
  }
  FilterView.prototype = Object.create(View.prototype, {constructor: {value: FilterView}});
  FilterView.prototype._execute = function (baseEntries) {
    return baseEntries.filter(this._filter);
  };
  
  function GroupView(db) {
    View.call(this, db);
  }
  GroupView.prototype = Object.create(View.prototype, {constructor: {value: GroupView}});
  GroupView.prototype._execute = function (baseEntries) {
    var lastFreqL = null;
    var lastFreqH = null;
    var lastGroup = [];
    var out = [];
    function flush() {
      if (lastGroup.length) {
        if (lastGroup.length > 1) {
          out.push(Object.freeze({
            type: 'group',
            lowerFreq: lastFreqL,
            upperFreq: lastFreqH,
            freq: (lastFreqL + lastFreqH) / 2,
            grouped: Object.freeze(lastGroup),
            n: Object.freeze({
              listen: function () {}
            })
          }));
        } else {
          out.push(lastGroup[0]);
        }
        lastGroup = [];
      }
    }
    baseEntries.forEach(function (record) {
      // TODO: not grouping bands is not on principle, it's just because FreqScale, the only user of this, doesn't want it. Revisit the design.
      if (record.type == 'band' || record.lowerFreq !== lastFreqL || record.upperFreq !== lastFreqH) {
        flush();
        lastFreqL = record.lowerFreq;
        lastFreqH = record.upperFreq;
      }
      lastGroup.push(record);
    });
    flush();
    return out;
  };
  
  // TODO: Consider switching Union to use a cell as its source. For that matter, consider switching the entire DB system to use DerivedCell — I think it has all the needed properties now. Though db sources don't need a scheduler baked in and DerivedCell does ...
  function Union() {
    this._unionSources = [];
    this._sourceGenerations = [];
    this._shrinking = false;
    this._entries = [];
    this._viewGeneration = 0;
    this._listeners = [];
    this._chainedListening = false;
    
    var notifier = new Notifier();
    function forward() {
      //console.log(this + ' forwarding');
      this._chainedListening = false;
      notifier.notify();
    }
    forward = forward.bind(this);
    this.n = {
      notify: notifier.notify.bind(notifier),
      listen: function (l) {
        if (!this._chainedListening) {
          //console.group(this + ' registering forwarder');
          this._chainedListening = true;
          forward.scheduler = l.scheduler; // TODO technically wrong
          this._unionSources.forEach(function (source) {
            source.n.listen(forward);
          });
          //console.groupEnd();
        } else {
          //console.log(this + ' locally registering listener');
        }
        notifier.listen(l);
      }.bind(this)
    };
  }
  Union.prototype = Object.create(Source.prototype, {constructor: {value: Union}});
  Union.prototype.toString = function () {
    return '[shinysdr.database.Union ' + this._unionSources + ']';
  };
  Union.prototype.add = function (source) {
    if (this._unionSources.indexOf(source) !== -1) return;
    this._unionSources.push(source);
    //console.log(this + ' firing notify for adding ' + source);
    this._chainedListening = false;  // no longer complete list
    this.n.notify();
  };
  Union.prototype.remove = function (source) {
    if (this._unionSources.indexOf(source) === -1) return;
    this._unionSources = this._unionSources.filter(function (x) { return x !== source; });
    this._sourceGenerations = [];  // clear obsolete info, will be fully rebuilt regardless
    this._shrinking = true;  // TODO kludge, can we not need this extra flag?
    this.n.notify();
  };
  Union.prototype.getSources = function () {  // used for db selection tree. TODO better interface
    return this._unionSources.slice();
  };
  Union.prototype.getAll = function () {
    if (!this._isUpToDate()) {
      var entries = [];
      this._unionSources.forEach(function (source, i) {
        entries.push.apply(entries, source.getAll());
        this._sourceGenerations[i] = source.getGeneration();
      }, this);
      entries.sort(compareRecord);
      this._entries = Object.freeze(entries);
      this._viewGeneration++;
      this._shrinking = false;
    }
    return this._entries;
  };
  Union.prototype.getGeneration = function () {
    return this._viewGeneration;
  };
  Union.prototype._isUpToDate = function () {
    return !this._shrinking && this._unionSources.every(function (source, i) {
      return source.getGeneration() === this._sourceGenerations[i] && source._isUpToDate();
    }.bind(this));
  };
  exports.Union = Union;
  
  function Table(label, writable, initializer, addURL) {
    writable = !!writable;
    this.n = new Notifier();
    View.call(this, this);
    this._viewGeneration = 0;
    this._label = label;
    this._triggerFacet = finishModification.bind(this);
    this._addURL = addURL;
    this.writable = !!writable;
    if (initializer) {
      initializer(function (suppliedRecord, url) {
        this._entries.push(new Record(suppliedRecord, url, writable ? this._triggerFacet : null));
      }.bind(this));
    }
  }
  // TODO: Make Table inherit only Source, not View, as it's not obvious what the resulting requirements for how View works are
  Table.prototype = Object.create(View.prototype, {constructor: {value: Table}});
  Table.prototype.getTableLabel = function () {  // TODO kludge, reconsider interface
    return this._label;
  };
  Table.prototype.toString = function () {
    return '[shinysdr.database.Table ' + this._label + ']';
  };
  Table.prototype.getAll = function () {
    var entries;
    if (!this._needsSort) {
      this._entries.sort(compareRecord);
    }
    return this._entries; // TODO return frozen
  };
  Table.prototype._isUpToDate = function () {
    return true;
  };
  Table.prototype.add = function (suppliedRecord) {
    if (!this.writable) {
      throw new Error('This table is read-only');
    }
    var record = new Record(suppliedRecord, null, this._triggerFacet);
    this._entries.push(record);
    this._triggerFacet();
    
    if (this._addURL) {
      record._remoteCreate(this._addURL);
    }
    
    return record;
  };
  exports.Table = Table;
  
  function arrayFromCatalog(url, callback) {
    //var union = new Union();
    var out = [];
    externalGet(url, 'document', function(indexDoc) {
      var anchors = indexDoc.querySelectorAll('a[href]');
      //console.log('Fetched database index with ' + anchors.length + ' links.');
      Array.prototype.forEach.call(anchors, function (anchor) {
        // Conveniently, the browser resolves URLs for us here
        out.push(fromURL(anchor.href));
      });
      callback(out);
    });
  };
  exports.arrayFromCatalog = arrayFromCatalog;
  
  function fromURL(url) {
    return new Table(
      decodeURIComponent(url.replace(/^.*\/(?=.)/, '').replace(/(.csv)?(\/)?$/, '')),
      true,
      function (internalAdd) {
        // TODO (implicitly) check mime type
        externalGet(url, 'text', function(jsonString) {
          JSON.parse(jsonString).forEach(function (record, i) {
            internalAdd(record, url + i);  // TODO: proper url resolution, urls from server.
          });
        });
      },
      url);
  }
  exports.fromURL = fromURL;
  
  function compareRecord(a, b) {
    return a.lowerFreq - b.lowerFreq;
  }
  
  function finishModification() {
    this._needsSort = true;
    this._viewGeneration++;
    //console.log(this + ' firing notify for modification');
    this.n.notify();
  }
  
  function OptCoord(record) {
    // might want to make this not _re_allocate at some point
    return record === null ? null : Object.freeze([+record[0], +record[1]]);
  }
  function OptNumber(value) {
    return value === null ? NaN : +value;
  }
  function makeRecordProp(name, coerce, defaultValue) {
    var internalName = '_stored_' + name;
    return {
      enumerable: true,
      get: function () {
        return this[internalName];
      },
      set: function (value) {
        if (this._initializing || this._hook) {
          if (this._initializing) {
            Object.defineProperty(this, internalName, {
              enumerable: false,
              writable: true,
              value: coerce(value)
            });
          } else {
            this[internalName] = coerce(value);
          }
          if (this._hook && !this._initializing) {
            (0, this._hook)();
          }
          this.n.notify();
        } else {
          throw new Error('This record is read-only');
        }
      },
      _my_default: defaultValue
    };
  }
  var recordProps = {
    type: makeRecordProp('type', String, 'channel'), // TODO enum constraint
    mode: makeRecordProp('mode', String, '?'),
    lowerFreq: makeRecordProp('lowerFreq', OptNumber, NaN),
    upperFreq: makeRecordProp('upperFreq', OptNumber, NaN),
    location: makeRecordProp('location', OptCoord, null),
    label: makeRecordProp('label', String, ''),
    notes: makeRecordProp('notes', String, '')
  };
  function Record(initial, url, changeHook) {
    if (url || changeHook) {
      this._url = url;
      
      // flags to avoid racing spammy updates
      var updating = false;
      var needAgain = false;
      var sendUpdate = function () {
        if (!this._oldState) throw new Error('too early');
        if (!this._url) return;
        if (updating) {
          needAgain = true;
          return;
        }
        updating = true;
        needAgain = false;
        var newState = this.toJSON();
        // TODO: PATCH method would be more specific
        xhrpost(this._url, JSON.stringify({old: this._oldState, new: newState}), function () {
          // TODO: Warn user / retry on network errors. Since we don't know whether the server has accepted the change we should retrieve it as new oldState and maybe merge
          updating = false;
          if (needAgain) sendUpdate();
        });
        this._oldState = newState;
      }.bind(this);
      
      this._hook = function() {
        if (changeHook) changeHook();
        // TODO: Changing lowerFreq + upperFreq sends double updates; see if we can coalesce
        sendUpdate();
      }.bind(this);
    } else {
      this._hook = null;
    }
    Object.defineProperties(this, {
      n: { enumerable: false, value: new Notifier() },
      _initializing: { enumerable: false, writable: true, value: true }
    });
    for (var name in recordProps) {
      this[name] = initial.propertyIsEnumerable(name) ? initial[name] : recordProps[name]._my_default;
    }
    if (isFinite(initial.freq)) {
      this.freq = initial.freq;
    }
    // TODO report unknown keys in initial
    this._initializing = false;
    this._oldState = this.toJSON();
    //Object.preventExtensions(this);  // TODO enable this after the _view_element kludge is gone
  }
  Object.defineProperties(Record.prototype, recordProps);
  Object.defineProperties(Record.prototype, {
    writable: {
      get: function () { return !!this._hook; }
    },
    freq: {
      get: function () {
        return (this.lowerFreq + this.upperFreq) / 2;
      },
      set: function (value) {
        this.lowerFreq = this.upperFreq = value;
      }
    },
    toJSON: { value: function () {
      var out = {};
      for (var k in this) {
        if (recordProps.hasOwnProperty(k)) {
          var value = this[k];
          if (typeof value === 'number' && isNaN(value)) value = null;  // JSON.stringify does this too; this is just to be canonical even if not stringified
          out[k] = value;
        }
      }
      return out;
    }},
    _remoteCreate: { value: function (addURL) {
      if (this._url) throw new Error('url already set');
      xhrpost(addURL, JSON.stringify({new: this.toJSON()}), function (r) {
        if (statusCategory(r.status) === 2) {
          if (this._url) throw new Error('url already set');
          this._url = r.getResponseHeader('Location');
          this._hook();  // write updates occurring before url was set
          
        } else {
          // TODO: retry/buffer creation or make the record defunct
          console.error('Record creation failed! ' + r.status, r);
        }
      }.bind(this));
      
    }}
  });
  
  function DatabasePicker(scheduler, sourcesCell, storage) {
    var self = this;
    var result = new Union();
    
    this._reshapeNotice = new Notifier();
    Object.defineProperty(this, '_reshapeNotice', {enumerable: false});
    this['_implements_shinysdr.client.database.DatabasePicker'] = true;
    Object.defineProperty(this, '_implements_shinysdr.client.database.DatabasePicker', {enumerable: false});
    this.getUnion = function () { return result; };    // TODO facet instead of giving add/remove access
    Object.defineProperty(this, 'getUnion', {enumerable: false});
    
    var i = 0;
    var sourceAKD = new AddKeepDrop(function addSource(source) {
      // TODO get clean stable unique names from the sources
      var label = source.getTableLabel ? source.getTableLabel() : (i++);
      var key = 'enabled_' + label; 
      var cell = new StorageCell(storage, Boolean, true, key);
      self[key] = cell;
      // TODO unbreakable notify loop. consider switching Union to work like, or to take a, DerivedCell.
      function updateUnionFromCell() {
        if (cell.depend(updateUnionFromCell)) {
          result.add(source);
        } else {
          result.remove(source);
        }
      }
      updateUnionFromCell.scheduler = scheduler;
      updateUnionFromCell();
      
      self._reshapeNotice.notify();
    }, function removeSource() {
      throw new Error('Removal not implemented');
    });
    
    // TODO generic glue copied from map-core.js, should be a feature of AddKeepDrop itself
    function dumpArray() {
      sourceAKD.begin();
      var array = sourcesCell.depend(dumpArray);
      array.forEach(function (feature) {
        sourceAKD.add(feature);
      });
      sourceAKD.end();
    }
    dumpArray.scheduler = scheduler;
    dumpArray();
  }
  exports.DatabasePicker = DatabasePicker;
  
  // Generic FM broadcast channels
  exports.fm = (function () {
    // Wikipedia currently says FM channels are numbered like so, but no one uses the numbers. Well, I'll use the numbers, just to start from integers. http://en.wikipedia.org/wiki/FM_broadcasting_in_the_USA
    return new Table('US FM broadcast', false, function (internalAdd) {
      for (var channel = 200; channel <= 300; channel++) {
        // not computing in MHz because that leads to roundoff error
        var freq = (channel - 200) * 2e5 + 879e5;
        internalAdd({
          type: 'channel',
          freq: freq,
          mode: 'WFM',
          label: 'FM ' /*+ channel*/ + (freq / 1e6).toFixed(1)
        });
      }
    });
  }());
  
  // Aircraft band channels
  exports.air = (function () {
    // http://en.wikipedia.org/wiki/Airband
    return new Table('US airband', false, function (internalAdd) {
      for (var freq = 108e6; freq <= 117.96e6; freq += 50e3) {
        internalAdd({
          type: 'channel',
          freq: freq,
          mode: '-',
          label: 'Air nav ' + (freq / 1e6).toFixed(2)
        });
      }
      for (var freq = 118e6; freq < 137e6; freq += 25e3) {
        internalAdd({
          type: 'channel',
          freq: freq,
          mode: 'AM',
          label: 'Air voice ' + (freq / 1e6).toFixed(2)
        });
      }
    });
  }());
  
  exports.systematics = Object.freeze([
    exports.fm,
    // TODO: This is currently too much clutter. Re-add this sort of info once we have ways to deemphasize repetitive information.
    //exports.air
  ])
  
  return Object.freeze(exports);
});