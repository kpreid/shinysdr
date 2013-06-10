var sdr = sdr || {};
(function () {
  'use strict';
  
  function DatabaseBase() {
    
  }
  DatabaseBase.prototype.getAll = function () {
    throw new Error('getAll not overridden!');
  };
  DatabaseBase.prototype.getGeneration = function () {
    throw new Error('getGeneration not overridden!');
  };
  DatabaseView.prototype.first = function () {
    return this.getAll()[0];
  };
  DatabaseView.prototype.last = function () {
    var entries = this.getAll();
    return entries[entries.length - 1];
  };
  DatabaseBase.prototype.inBand = function (lower, upper) {
    return new DatabaseView(this, function inBandFilter(record) {
      return (record.freq || record.upperFreq) >= lower &&
             (record.freq || record.lowerFreq) <= upper;
    });
  };
  DatabaseBase.prototype.type = function (type) {
    return new DatabaseView(this, function typeFilter(record) {
      return record.type === type;
    });
  };
  DatabaseBase.prototype.string = function (str) {
    var re = new RegExp(str, 'i');
    return new DatabaseView(this, function stringFilter(record) {
      return re.test(record.label) || re.test(record.notes);
    });
  };
  DatabaseBase.prototype.forEach = function (f) {
    this.getAll().forEach(f);
  };
  
  function DatabaseView(db, filter) {
    this._viewGeneration = NaN;
    this._entries = [];
    this._db = db;
    this._filter = filter;
    this.n = this._db.n;
  }
  DatabaseView.prototype = Object.create(DatabaseBase.prototype, {constructor: {value: DatabaseView}});
  DatabaseView.prototype._isUpToDate = function () {
    return this._viewGeneration === this._db._viewGeneration && this._db._isUpToDate();
  };
  DatabaseView.prototype.getAll = function (callback) {
    var entries;
    if (!this._isUpToDate()) {
      this._entries = Object.freeze(this._db.getAll().filter(this._filter));
      this._viewGeneration = this._db._viewGeneration;
    }
    return this._entries;
  };
  DatabaseView.prototype.getGeneration = function () {
    return this._viewGeneration;
  };
  
  function Database() {
    this.n = new sdr.events.Notifier();
    DatabaseView.call(this, this);
    this._viewGeneration = 0;
  }
  Database.prototype = Object.create(DatabaseView.prototype, {constructor: {value: Database}});
  Database.prototype._isUpToDate = function () {
    return true;
  };
  // Generic FM channels
  Database.prototype.addFM = function () {
    // Wikipedia currently says FM channels are numbered like so, but no one uses the numbers. Well, I'll use the numbers, just to start from integers. http://en.wikipedia.org/wiki/FM_broadcasting_in_the_USA
    for (var channel = 200; channel <= 300; channel++) {
      // not computing in MHz because that leads to roundoff error
      var freq = (channel - 200) * 2e5 + 879e5;
      this._entries.push({
        type: 'channel',
        freq: freq,
        mode: 'WFM',
        label: 'FM ' /*+ channel*/ + (freq / 1e6).toFixed(1)
      });
    }
    finishModification.call(this);
  };
  // Aircraft band channels
  Database.prototype.addAir = function () {
    // http://en.wikipedia.org/wiki/Airband
    for (var freq = 108e6; freq <= 117.96e6; freq += 50e3) {
      this._entries.push({
        type: 'channel',
        freq: freq,
        mode: '-',
        label: 'Air nav ' + (freq / 1e6).toFixed(2)
      });
    }
    for (var freq = 118e6; freq < 137e6; freq += 25e3) {
      this._entries.push({
        type: 'channel',
        freq: freq,
        mode: 'AM',
        label: 'Air voice ' + (freq / 1e6).toFixed(2)
      });
    }
    finishModification.call(this);
  };
  Database.prototype.addAllSystematic = function () {
    this.addFM();
    
    // TODO: This is currently too much clutter. Re-add this sort of info once we have ways to deemphasize repetitive information.
    //this.addAir();
  };
  // Read the given resource as an index containing links to CSV files in Chirp <http://chirp.danplanet.com/> generic format. No particular reason for choosing Chirp other than it was a the first source and format of machine-readable channel data I found to experiment with.
  Database.prototype.addFromCatalog = function (url) {
    // TODO: refactor this code
    var self = this;
    sdr.network.externalGet(url, 'document', function(indexDoc) {
      var anchors = indexDoc.querySelectorAll('a[href]');
      //console.log('Fetched database index with ' + anchors.length + ' links.');
      Array.prototype.forEach.call(anchors, function (anchor) {
        // Conveniently, the browser resolves URLs for us here
        //console.log(anchor.href);
        sdr.network.externalGet(anchor.href, 'text', function(csv) {
          console.group('Parsing ' + anchor.href);
          var csvLines = csv.split(/[\r\n]+/);
          var columns = csvLines.shift().split(/,/);
          csvLines.forEach(function (line, lineNoBase) {
            var lineNo = lineNoBase + 2;
            function error(msg) {
              console.error(anchor.href + ':' + lineNo + ': ' + msg + '\n' + line + '\n', fields, '\n', record);
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
            self._entries.push(entry);
          });
          console.groupEnd();

          finishModification.call(self);
        });
      });
    });
  };
  
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
  
  sdr.Database = Database;
}());