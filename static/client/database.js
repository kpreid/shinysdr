var sdr = sdr || {};
(function () {
  'use strict';
  
  var STOP = {};
  
  function DatabaseView(db, filter) {
    this._viewGeneration = 0;
    this._entries = [];
    this._db = db;
    this._filter = filter;
  }
  DatabaseView.prototype.forEach = function (callback) {
    var entries;
    if (this._viewGeneration < this._db._viewGeneration) {
      var filter = this._filter;
      entries = [];
      this._db.forEach(function(record) {
        if (filter(record)) {
          entries.push(record);
        }
      });
      this._entries = entries;
      this._viewGeneration = this._db._viewGeneration;
    } else {
      entries = this._entries;
    }
    var n = entries.length;
    for (var i = 0; i < n; i++) {
      var ret = callback(entries[i]);
      if (ret === STOP) return;
    }
  };
  DatabaseView.prototype.first = function () {
    var filter = this._filter;
    if (this._viewGeneration < this._db._viewGeneration) {
      var got;
      this._db.forEach(function(record) {
        if (filter(record)) {
          got = record;
          return STOP;
        }
      });
      return got;
    } else {
      return this._entries[0];
    }
  };
  DatabaseView.prototype.inBand = function (lower, upper) {
    return new DatabaseView(this, function (record) {
      return record.freq >= lower && record.freq <= upper;
    });
  };
  DatabaseView.prototype.string = function (str) {
    var re = new RegExp(str, 'i');
    return new DatabaseView(this, re.test.bind(re));
  };
  DatabaseView.prototype.getGeneration = function () {
    return this._viewGeneration;
  };
  
  function Database() {
    DatabaseView.call(this, this);
  }
  Database.prototype = Object.create(DatabaseView.prototype, {constructor: {value: Database}});
  // Generic FM channels
  Database.prototype.addFM = function () {
    // Wikipedia currently says FM channels are numbered like so, but no one uses the numbers. Well, I'll use the numbers, just to start from integers. http://en.wikipedia.org/wiki/FM_broadcasting_in_the_USA
    for (var channel = 200; channel <= 300; channel++) {
      // not computing in MHz because that leads to roundoff error
      var freq = (channel - 200) * 2e5 + 879e5;
      this._entries.push({
        freq: freq,
        mode: 'WFM',
        label: 'FM ' /*+ channel*/ + (freq / 1e6).toFixed(1)
      });
    }
    this._viewGeneration++;
  };
  // Read the given resource as an index containing links to CSV files in Chirp <http://chirp.danplanet.com/> generic format. No particular reason for choosing Chirp other than it was a the first source and format of machine-readable channel data I found to experiment with.
  Database.prototype.addFromCatalog = function (url) {
    // TODO: refactor this code
    var self = this;
    sdr.network.externalGet(url, 'document', function(indexDoc) {
      console.log(indexDoc);
      var anchors = indexDoc.querySelectorAll('a[href]');
      //console.log('Fetched database index with ' + anchors.length + ' links.');
      Array.prototype.forEach.call(anchors, function (anchor) {
        // Conveniently, the browser resolves URLs for us here
        //console.log(anchor.href);
        sdr.network.externalGet(anchor.href, 'text', function(csv) {
          console.group(anchor.href);
          var csvLines = csv.split(/[\r\n]+/);
          var columns = csvLines.shift().split(/,/);
          csvLines.forEach(function (line) {
            if (/^\s*$/.test(line)) return;
            var fields = line.split(/,/); // TODO handle quotes
            var record = Object.create(null);
            columns.forEach(function (name, index) {
              record[name] = fields[index];
            });
            var freqMHz = parseFloat(record.Frequency);
            if (isNaN(freqMHz)) {
              console.log('Bad freq!', line, record);
            }
            self._entries.push({
              freq: freqMHz * 1e6,
              // TODO: Not sure what distinction the data is actually making
              mode: record.Mode === 'FM' ? 'NFM' : record.Mode || '',
              label: record.Name || '',
              notes: record.Comment || ''
            });
          });
          console.groupEnd();

          self._entries.sort(function(a, b) { return a.freq - b.freq; });
        });
      });
    });
    this._viewGeneration++;
  };
  
  sdr.Database = Database;
}());