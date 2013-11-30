// Copyright 2013 Kevin Reid <kpreid@switchb.org>
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

define(['./values', './events'], function (values, events) {
  'use strict';
  
  var Cell = values.Cell;
  var typeFromDesc = values.typeFromDesc;
  
  var exports = {};
  
  function identity(x) { return x; }
  
  function statusCategory(httpStatus) {
    return Math.floor(httpStatus / 100);
  }
  exports.statusCategory = statusCategory;
  
  function makeXhrStateCallback(r, whenReady) {
    return function() {
      if (r.readyState === 4) {
        whenReady(r);
      }
    };
  }
  
  function xhrput(url, data, opt_callback) {
    var r = new XMLHttpRequest();
    r.open('PUT', url, true);
    r.setRequestHeader('Content-Type', 'application/json');
    r.onreadystatechange = makeXhrStateCallback(r,
      function putDone(r) {
        if (opt_callback) opt_callback(r);
      });
    r.send(data);
    console.log(url, data);
  }
  exports.xhrput = xhrput;
  
  function xhrpost(url, data, opt_callback) {
    var r = new XMLHttpRequest();
    r.open('POST', url, true);
    r.setRequestHeader('Content-Type', 'application/json');
    r.onreadystatechange = makeXhrStateCallback(r,
      function postDone(r) {
        if (opt_callback) opt_callback(r);
      });
    r.send(data);
    console.log(url, data);
  }
  exports.xhrpost = xhrpost;
  
  function xhrdelete(url, opt_callback) {
    var r = new XMLHttpRequest();
    r.open('DELETE', url, true);
    r.onreadystatechange = makeXhrStateCallback(r,
      function delDone(r) {
        if (opt_callback) opt_callback(r);
      });
    r.send();
    console.log('DELETE', url);
  }
  exports.xhrdelete = xhrdelete;
  
  function externalGet(url, responseType, callback) {
    var r = new XMLHttpRequest();
    r.responseType = responseType;
    r.onreadystatechange = function() {
      if (r.readyState === 4) {
        if (statusCategory(r.status) == 2) {
          callback(r.response);
        } else {
          //TODO error handling in UI
        }
      }
    };
    r.open('GET', url, true);
    r.send();
  }
  exports.externalGet = externalGet;
  
  function ReadWriteCell(name, assumed, type) {
    Cell.call(this, type);
    var value = assumed;
    var remoteValue = assumed;
    var inhibit = 0;
    var resetTimeout = undefined;
    this.get = function() { return value; },
    this.set = function(newValue) {
      value = newValue;
      this.n.notify();
      inhibit = Date.now() + 1000;  // TODO adjust value to observed latency
      xhrput(name, JSON.stringify(newValue), function(r) {
        if (statusCategory(r.status) !== 2) {
          // some error or something other than success; revert
          inhibit = 0;
          this._update(remoteValue);
        }
      }.bind(this));
    };
    this._update = function(newValue) {
      remoteValue = newValue;
      if (resetTimeout) clearTimeout(resetTimeout);
      resetTimeout = setTimeout(acceptFromNetwork, Math.max(0, inhibit - Date.now()));
    };
    var acceptFromNetwork = function() {
      value = remoteValue;
      this.n.notify();
    }.bind(this);
  }
  ReadWriteCell.prototype = Object.create(Cell.prototype, {constructor: {value: ReadWriteCell}});
  exports.ReadWriteCell = ReadWriteCell;
  
  function ReadCell(name, /* initial */ value, type, transform) {
    Cell.call(this, type);
    
    this._update = function(data) {
      value = transform(data);
      this.n.notify();
    }.bind(this);
    
    this.get = function() {
      return value;
    };
  }
  ReadCell.prototype = Object.create(Cell.prototype, {constructor: {value: ReadCell}});
  exports.ReadCell = ReadCell;
  
  function SpectrumCell(url) {
    var fft = new Float32Array(0);
    var swapbuf = new Float32Array(0);
    var VSIZE = Float32Array.BYTES_PER_ELEMENT;
    var centerFreq = NaN;
    var sampleRate = NaN;

    // kludge to ensure that widgets get all of the frames
    // TODO: put this on a more general and sound framework
    var subscriptions = [];
    
    function transform(json) {
      if (json === null) {
        // occurs when server is paused on load — TODO fix server so it always returns an array
        return fft;
      }
      var info = json[0];
      centerFreq = info[0];
      sampleRate = info[1];
      var arrayFFT = json[1];

      var halfFFTSize = arrayFFT.length / 2;

      // adjust size if needed
      if (arrayFFT.length !== fft.length) {
        fft = new Float32Array(arrayFFT.length);
        swapbuf = new Float32Array(arrayFFT.length);
      }
      
      // swap first and second halves for drawing convenience so that center frequency is at halfFFTSize rather than 0
      swapbuf.set(arrayFFT);
      fft.set(swapbuf.subarray(0, halfFFTSize), halfFFTSize);
      fft.set(swapbuf.subarray(halfFFTSize, fft.length), 0);
      
      var bundled = [info, fft];
      // TODO replace this with something async (note that fft is mutated so we need to allocate or use a free-list/circular-buffer strategy)
      for (var i = 0; i < subscriptions.length; i++) {
        (0,subscriptions[i])(bundled);
      }
      
      return fft;
    }
    
    ReadCell.call(this, url, fft, values.any, transform);
    
    this.getCenterFreq = function() {
      return centerFreq;
    };
    this.getSampleRate = function() {
      return sampleRate;
    };
    this.subscribe = function(callback) {
      // TODO need to provide for unsubscribing
      subscriptions.push(callback);
      callback([[centerFreq, sampleRate], fft]);
    };
  }
  SpectrumCell.prototype = Object.create(ReadCell.prototype, {constructor: {value: SpectrumCell}});
  exports.SpectrumCell = SpectrumCell;
  
  function setNonEnum(o, p, v) {
    Object.defineProperty(o, p, {
      value: v,
      configurable: true
    })
  }
  
  function openWebSocket(path) {
    // TODO: Have server deliver websocket URL, remove port number requirement
    if (!/^\//.test(path)) throw new Error('bad path');
    var secure = document.location.protocol === 'http:' ? '' : 's';
    var ws = new WebSocket('ws' + secure + '://' + document.location.hostname + ':' + (parseInt(document.location.port) + 1) + document.location.pathname.replace(/\/$/, '') + path);
    ws.addEventListener('open', function (event) {
      ws.send(''); // dummy required due to server limitation
    }, true);
    return ws;
  }
  exports.openWebSocket = openWebSocket;
  
  var minRetryTime = 1000;
  var maxRetryTime = 20000;
  var backoff = 1.05;
  function retryingConnection(path, callback) {
    var timeout = minRetryTime;
    var succeeded = false;
    function go() {
      var ws = openWebSocket(path);
      ws.addEventListener('open', function (event) {
        succeeded = true;
        timeout = minRetryTime;
      }, true);
      ws.addEventListener('close', function (event) {
        if (succeeded) {
          console.error('Lost WebSocket connection', path);
        } else {
          timeout = Math.min(maxRetryTime, timeout * backoff);
        }
        succeeded = false;
        setTimeout(go, timeout);
      }, true);
      callback(ws);
    }
    go();
  };
  exports.retryingConnection = retryingConnection;
  
  function makeBlock(url) {
    var block = {};
    // TODO kludges, should be properly facetized and separately namespaced somehow
    setNonEnum(block, '_url', url);
    setNonEnum(block, '_reshapeNotice', new events.Notifier());
    setNonEnum(block, 'create', function(desc) {
      // TODO arrange a callback with the resulting _object_
      xhrpost(url, JSON.stringify(desc));
    });
    setNonEnum(block, 'delete', function(key) {
      xhrdelete(url + '/' + encodeURIComponent(key));
    });
    return block;
  }
  
  function makeCell(url, desc, idMap) {
    var cell;
    if (desc.type === 'spectrum') {
      // TODO eliminate special case
      cell = new SpectrumCell(url);
    } else if (desc.kind === 'block') {
      // TODO eliminate special case by making server block cells less special?
      cell = new ReadCell(url, /* dummy */ makeBlock(url), values.block,
        function (id) { return idMap[id]; });
    } else if (desc.writable) {
      cell = new ReadWriteCell(url, desc.current, typeFromDesc(desc.type));
    } else {
      cell = new ReadCell(url, desc.current, typeFromDesc(desc.type), identity);
    }
    return [cell, cell._update];
  }
  
  function connect(rootURL, scheduler, callback) {
    var rootCell = new ReadCell(null, null, values.block, identity);
    
    // TODO: URL contents are no longer actually used. URL should be used to derive state stream URL
    //externalGet(rootURL, 'text', function(text) { ... });

    retryingConnection('/state', function(ws) {
      ws.binaryType = 'arraybuffer';

      var idMap = Object.create(null);
      var updaterMap = Object.create(null);
      var isCellMap = Object.create(null);
      
      idMap[0] = rootCell;
      updaterMap[0] = function (id) { rootCell._update(idMap[id]); };
      isCellMap[0] = true;
      
      function oneMessage(message) {
        var op = message[0];
        var id = message[1];
        switch (message[0]) {
          case 'register_block':
            var url = message[2];
            updaterMap[id] = idMap[id] = makeBlock(url);
            isCellMap[id] = false;
            break;
          case 'register_cell':
            var url = message[2];
            var desc = message[3];
            var pair = makeCell(url, desc, idMap);
            idMap[id] = pair[0];
            updaterMap[id] = pair[1];
            isCellMap[id] = true;
            break;
          case 'value':
            var value = message[2];
            if (!(id in idMap)) {
              console.error('Undefined id in state stream message', message);
              return;
            }
            if (isCellMap[id]) {
              (0, updaterMap[id])(value);
            } else {
              // is block
              var block = idMap[id];
              for (var k in block) { delete block[k]; }
              for (var k in value) {
                block[k] = idMap[value[k]];
              }
              block._reshapeNotice.notify();
            }
            break;
          case 'delete':
            // TODO: explicitly invalidate the objects so we catch hanging on to them too long
            delete idMap[id];
            delete updaterMap[id];
            delete isCellMap[id];
            break;
          default:
            console.error('unknown state stream message', message);
        }
      }
      
      function oneBinaryMessage(buffer) {
        // Currently, SpectrumCell updates are the only type of binary messages.
        var view = new DataView(buffer);
        var id = view.getUint32(0, true);
        var freq = view.getFloat64(4, true);
        var rate = view.getFloat64(4+8, true);
        var data = new Float32Array(buffer, 4+8+8);
        //console.log(id, freq, rate, data.length);
        (0, updaterMap[id])([[freq, rate], data]);
      }
      
      ws.onmessage = function (event) {
        // TODO: close connection on exception here
        if (typeof event.data === 'string') {
          JSON.parse(event.data).forEach(oneMessage);
        } else if (event.data instanceof ArrayBuffer) {
          oneBinaryMessage(event.data);
        } else {
          console.error('Unknown object from state stream onmessage:', event.data);
        }
      };
      
    });

    function ready() {
      callback(rootCell.get(), rootCell);
    }
    ready.scheduler = scheduler;
    rootCell.n.listen(ready);
  }
  exports.connect = connect;
  
  return Object.freeze(exports);
});