define(['./events', './network'], function (events, network) {
  'use strict';
  
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
      return (record.freq || record.upperFreq) >= lower &&
             (record.freq || record.lowerFreq) <= upper;
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
  function csvStr(s) {
    if (/^[^,\n"]*$/.test(s)) {
      return s;
    } else {
      return '"' + s.replace('"', '""') + '"';
    }
  }
  function freqStr(f) {
    return String(f / 1e6);
  }
  Source.prototype.toCSV = function () {
    var out = ['Mode,Frequency,Name,Comment\n'];
    this.forEach(function (record) {
      var freq = 'freq' in record ? freqStr(record.freq) :
                 freqStr(record.lowerFreq) + '-' + freqStr(record.upperFreq);
      var fields = [freq, record.mode, record.label, record.notes];
      out.push(fields.map(csvStr).join(',') + '\n');
    });
    return out.join('');
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
    var lastFreq = null;
    var lastGroup = [];
    var out = [];
    function flush() {
      if (lastGroup.length) {
        if (lastGroup.length > 1) {
          out.push(Object.freeze({
            type: 'group',
            freq: lastFreq,
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
      if ('freq' in record) {
        if (record.freq !== lastFreq) {
          flush();
          lastFreq = record.freq;
        }
        lastGroup.push(record);
      } else {
        flush();
        out.push(record);
      }
    });
    flush();
    return out;
  };
  
  function Union() {
    this._unionSources = [];
    this._sourceGenerations = [];
    this._entries = [];
    this._viewGeneration = 0;
    this._listeners = [];
    this._chainedListening = false;
    
    var notifier = new events.Notifier();
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
    this._unionSources.push(source);
    //console.log(this + ' firing notify for adding ' + source);
    this._chainedListening = false;  // no longer complete list
    this.n.notify();
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
    }
    return this._entries;
  };
  Union.prototype.getGeneration = function () {
    return this._viewGeneration;
  };
  Union.prototype._isUpToDate = function () {
    return this._unionSources.every(function (source, i) {
      return source.getGeneration() === this._sourceGenerations[i] && source._isUpToDate();
    }.bind(this));
  };
  exports.Union = Union;
  
  function Table(label, writable, initializer) {
    writable = !!writable;
    this.n = new events.Notifier();
    View.call(this, this);
    this._viewGeneration = 0;
    this._label = label;
    this._triggerFacet = finishModification.bind(this);
    this.writable = !!writable;
    if (initializer) {
      initializer(function (suppliedRecord) {
        this._entries.push(new Record(suppliedRecord, writable ? this._triggerFacet : null));
      }.bind(this));
    }
  }
  // TODO: Make Table inherit only Source, not View, as it's not obvious what the resulting requirements for how View works are
  Table.prototype = Object.create(View.prototype, {constructor: {value: Table}});
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
    var record = new Record(suppliedRecord, this._triggerFacet);
    this._entries.push(record);
    this._triggerFacet();
    return record;
  };
  exports.Table = Table;
  
  function fromCatalog(url) {
    var union = new Union();
    network.externalGet(url, 'document', function(indexDoc) {
      var anchors = indexDoc.querySelectorAll('a[href]');
      //console.log('Fetched database index with ' + anchors.length + ' links.');
      Array.prototype.forEach.call(anchors, function (anchor) {
        // Conveniently, the browser resolves URLs for us here
        union.add(fromURL(anchor.href));
      });
    });
    return union;
  };
  exports.fromCatalog = fromCatalog;
  
  function fromURL(url) {
    return new Table(
      decodeURIComponent(url.replace(/^.*\//, '')),
      true,
      function (internalAdd) {
        // TODO (implicitly) check mime type
        network.externalGet(url, 'text', function(jsonString) {
          JSON.parse(jsonString).forEach(internalAdd);
        });
      });
  }
  exports.fromURL = fromURL;
  
  function compareRecord(a, b) {
    return (a.freq || a.lowerFreq) - (b.freq || b.lowerFreq);
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
  function makeRecordProp(name, coerce, defaultValue) {
    var internalName = '_stored_' + name;
    return {
      enumerable: true,
      get: function () {
        return this[internalName];
      },
      set: function (value) {
        if (this._initializing || this._hook) {
          this[internalName] = coerce(value);
          if (this._hook) {
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
    freq: makeRecordProp('freq', Number, NaN), // TODO only for channel
    lowerFreq: makeRecordProp('lowerFreq', Number, NaN),  // TODO only for band
    upperFreq: makeRecordProp('upperFreq', Number, NaN),  // TODO only for band
    location: makeRecordProp('location', OptCoord, null),
    label: makeRecordProp('label', String, ''),
    notes: makeRecordProp('notes', String, '')
  };
  function Record(initial, changeHook) {
    this._hook = changeHook;
    this.n = new events.Notifier();
    this._initializing = true;
    for (var name in recordProps) {
      this[name] = initial.propertyIsEnumerable(name) ? initial[name] : recordProps[name]._my_default;
    }
    this._initializing = false;
    //Object.preventExtensions(this);  // TODO enable this after the _view_element kludge is gone
  }
  Object.defineProperties(Record.prototype, recordProps);
  Object.defineProperties(Record.prototype, {
    writable: {
      get: function () { return !!this._hook; }
    }
  });
  
  // Generic FM broadcast channels
  exports.fm = (function () {
    // Wikipedia currently says FM channels are numbered like so, but no one uses the numbers. Well, I'll use the numbers, just to start from integers. http://en.wikipedia.org/wiki/FM_broadcasting_in_the_USA
    return new Table('builtin FM', false, function (internalAdd) {
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
    return new Table('builtin air', false, function (internalAdd) {
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
  
  exports.allSystematic = new Union();
  exports.allSystematic.add(exports.fm);
  // TODO: This is currently too much clutter. Re-add this sort of info once we have ways to deemphasize repetitive information.
  //exports.allSystematic.add(exports.air);
  
  return Object.freeze(exports);
});