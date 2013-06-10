var sdr = sdr || {};
(function () {
  'use strict';
  
  var database = {};
  
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
    return new View(this, function inBandFilter(record) {
      return (record.freq || record.upperFreq) >= lower &&
             (record.freq || record.lowerFreq) <= upper;
    });
  };
  Source.prototype.type = function (type) {
    return new View(this, function typeFilter(record) {
      return record.type === type;
    });
  };
  Source.prototype.string = function (str) {
    var re = new RegExp(str, 'i');
    return new View(this, function stringFilter(record) {
      return re.test(record.label) || re.test(record.notes);
    });
  };
  Source.prototype.forEach = function (f) {
    this.getAll().forEach(f);
  };
  
  function View(db, filter) {
    this._viewGeneration = NaN;
    this._entries = [];
    this._db = db;
    this._filter = filter;
    this.n = this._db.n;
  }
  View.prototype = Object.create(Source.prototype, {constructor: {value: View}});
  View.prototype._isUpToDate = function () {
    return this._viewGeneration === this._db._viewGeneration && this._db._isUpToDate();
  };
  View.prototype.getAll = function (callback) {
    var entries;
    if (!this._isUpToDate()) {
      this._entries = Object.freeze(this._db.getAll().filter(this._filter));
      this._viewGeneration = this._db.getGeneration();
    }
    return this._entries;
  };
  View.prototype.getGeneration = function () {
    return this._viewGeneration;
  };
  
  function Union() {
    this._unionSources = [];
    this._sourceGenerations = [];
    this._entries = [];
    this._viewGeneration = NaN;
    this._listeners = [];
    
    var notifier = new sdr.events.Notifier();
    var listening = false;
    function forward() {
      listening = false;
      notifier.notify();
    }
    this.n = {
      notify: notifier.notify.bind(notifier),
      listen: function (l) {
        if (!listening) {
          listening = true;
          forward.scheduler = l.scheduler; // TODO technically wrong
          this._unionSources.forEach(function (source) {
            source.n.listen(forward);
          });
        }
        notifier.listen(l);
      }.bind(this)
    };
  }
  Union.prototype = Object.create(Source.prototype, {constructor: {value: Union}});
  Union.prototype.add = function (source) {
    this._unionSources.push(source);
    this.n.notify();
  };
  Union.prototype.getAll = function () {
    if (!this._isUpToDate()) {
      var entries = [];
      this._unionSources.forEach(function (source) {
        entries.push.apply(entries, source.getAll());
      });
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
      return source.getGeneration() === this._sourceGenerations[i];
    }.bind(this));
  };
  database.Union = Union;
  
  function Table() {
    this.n = new sdr.events.Notifier();
    View.call(this, this);
    this._viewGeneration = 0;
  }
  Table.prototype = Object.create(View.prototype, {constructor: {value: Table}});
  Table.prototype._isUpToDate = function () {
    return true;
  };
  Table.prototype.add = function (entry) {
    // TODO validate
    this._entries.push(entry);
    finishModification.call(this); // TODO lazy after multiple adds
  };
  database.Table = Table;
  
  function fromCatalog(url) {
    var union = new Union();
    sdr.network.externalGet(url, 'document', function(indexDoc) {
      var anchors = indexDoc.querySelectorAll('a[href]');
      //console.log('Fetched database index with ' + anchors.length + ' links.');
      Array.prototype.forEach.call(anchors, function (anchor) {
        // Conveniently, the browser resolves URLs for us here
        union.add(fromCSV(anchor.href));
      });
    });
    return union;
  };
  database.fromCatalog = fromCatalog;
  
  // Read the given resource as an index containing links to CSV files in Chirp <http://chirp.danplanet.com/> generic format. No particular reason for choosing Chirp other than it was a the first source and format of machine-readable channel data I found to experiment with.
  function fromCSV(url) {
    var table = new Table();
    sdr.network.externalGet(url, 'text', function(csv) {
      console.group('Parsing ' + url);
      var csvLines = csv.split(/[\r\n]+/);
      var columns = csvLines.shift().split(/,/);
      csvLines.forEach(function (line, lineNoBase) {
        var lineNo = lineNoBase + 2;
        function error(msg) {
          console.error(url + ':' + lineNo + ': ' + msg + '\n' + line + '\n', fields, '\n', record);
        }
        if (/^\s*$/.test(line)) return; // allow whitespace
        var fields = parseCSVLine(line);
        if (fields.length > columns.length) {
          error('Too many fields');
        }
        var record = Object.create(null);
        columns.forEach(function (name, index) {
          record[name] = fields[index];
        });
        var entry = {
          // TODO: Not sure what distinction the data is actually making
          mode: record.Mode === 'FM' ? 'NFM' : record.Mode || '',
          label: record.Name || '',
          notes: record.Comment || ''
        };
        var match;
        if ((match = /^(\d+(?:\.\d+)?)(?:\s*-\s*(\d+(?:\.\d+)?))?$/.exec(record.Frequency))) {
          if (match[2]) {
            entry.type = 'band';
            entry.lowerFreq = 1e6 * parseFloat(match[1]);
            entry.upperFreq = 1e6 * parseFloat(match[2]);
          } else {
            entry.type = 'channel';
            entry.freq = 1e6 * parseFloat(match[1]);
          }
        } else {
          error('Bad frequency value');
        }
        table._entries.push(entry); // TODO better bulk mutation interface
      });
      console.groupEnd();

      finishModification.call(table);
    });
    return table;
  }
  database.fromCSV = fromCSV;

  function compareRecord(a, b) {
    return (a.freq || a.lowerFreq) - (b.freq || b.lowerFreq);
  }
  
  function finishModification() {
    this._entries.sort(compareRecord);
    this._viewGeneration++;
    this.n.notify();
  }
  
  function parseCSVLine(line) {
    var fields = [];
    var start = 0;
    var sanity = 0;
    for (;sanity++ < 1000;) {
      if (line[start] === '"') {
        //debugger;
        start++;
        var text = '';
        for (;;) {
          var end = line.indexOf('"', start);
          if ('end' === -1) {
            console.warn('CSV unclosed quote', line[start]);
            break;
          } else {
            text += start === end ? '"' : line.slice(start, end);
            start = end + 1;
            if (line[start] === '"') {
              start++;
              // continue quote parser
            } else if (start >= line.length || line[start] === ',') {
              start++;
              break; // done with quote parsing
            } else {
              console.warn('CSV garbage after quote', line[start]);
              break;
            }
          }
        }
        fields.push(text);
        if (start > line.length) {
          break;
        }
      } else {
        var end = line.indexOf(',', start);
        if (end === -1) {
          fields.push(line.slice(start));
          break;
        } else {
          fields.push(line.slice(start, end));
          start = end + 1;
        }
      }
    }
    return fields;
  }
  
  // Generic FM broadcast channels
  database.fm = (function () {
    // Wikipedia currently says FM channels are numbered like so, but no one uses the numbers. Well, I'll use the numbers, just to start from integers. http://en.wikipedia.org/wiki/FM_broadcasting_in_the_USA
    var table = new Table();
    for (var channel = 200; channel <= 300; channel++) {
      // not computing in MHz because that leads to roundoff error
      var freq = (channel - 200) * 2e5 + 879e5;
      table.add({
        type: 'channel',
        freq: freq,
        mode: 'WFM',
        label: 'FM ' /*+ channel*/ + (freq / 1e6).toFixed(1)
      });
    }
    return table;
  }());
  
  // Aircraft band channels
  database.air = (function () {
    // http://en.wikipedia.org/wiki/Airband
    var table = new Table();
    for (var freq = 108e6; freq <= 117.96e6; freq += 50e3) {
      table.add({
        type: 'channel',
        freq: freq,
        mode: '-',
        label: 'Air nav ' + (freq / 1e6).toFixed(2)
      });
    }
    for (var freq = 118e6; freq < 137e6; freq += 25e3) {
      table.add({
        type: 'channel',
        freq: freq,
        mode: 'AM',
        label: 'Air voice ' + (freq / 1e6).toFixed(2)
      });
    }
    return table;
  }());
  
  database.allSystematic = new Union();
  database.allSystematic.add(database.fm);
  // TODO: This is currently too much clutter. Re-add this sort of info once we have ways to deemphasize repetitive information.
  //database.allSystematic.add(database.air);
  
  sdr.database = Object.freeze(database);
}());