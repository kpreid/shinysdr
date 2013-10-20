define(['./values', './events'], function (values, events) {
  'use strict';
  
  var Cell = values.Cell;
  var typeFromDesc = values.typeFromDesc;
  
  var exports = {};
  
  function identity(x) { return x; }
  
  // Connectivity management
  var isDown = false;
  var queuedToRetry = Object.create(null);
  var isDownCheckXHR = new XMLHttpRequest();
  var isDownCheckInterval;
  isDownCheckXHR.onreadystatechange = function() {
    if (isDownCheckXHR.readyState === 4) {
      if (isDownCheckXHR.status > 0 && isDownCheckXHR.status < 500) {
        isDown = false;
        clearInterval(isDownCheckInterval);
        for (var key in queuedToRetry) {
          var retrier = queuedToRetry[key];
          delete queuedToRetry[key];
          retrier();
        }
      }
    }
  };
  function isDownCheck() {
    isDownCheckXHR.open('HEAD', '/', true);
    isDownCheckXHR.send();
  }
  
  function statusCategory(httpStatus) {
    return Math.floor(httpStatus / 100);
  }
  
  function makeXhrStateCallback(r, retry, whenReady, whenOther) {
    return function() {
      if (r.readyState === 4) {
        if (r.status === 0) {
          // network error
          if (!isDown) {
            console.log('Network error, suspending activities');
            isDown = true;
            isDownCheckInterval = setInterval(isDownCheck, 1000);
          }
          retry();  // cause enqueueing under isDown condition
          return;
        }
        isDown = false;
        whenReady(r);
      }
    };
  }
  
  function xhrput(url, data, opt_callback) {
    if (isDown) {
      queuedToRetry['PUT ' + url] = function() { xhrput(url, data); };
      return;
    }
    var r = new XMLHttpRequest();
    r.open('PUT', url, true);
    r.setRequestHeader('Content-Type', 'application/json');
    r.onreadystatechange = makeXhrStateCallback(r,
      function putRetry() {
        xhrput(url, data); // causes enqueueing
      },
      function putDone(r) {
        if (opt_callback) opt_callback(r);
      });
    r.send(data);
    console.log(url, data);
  }
  exports.xhrput = xhrput;
  
  function xhrpost(url, data, opt_callback) {
    // TODO add retry behavior (once we know our idempotence story)
    var r = new XMLHttpRequest();
    r.open('POST', url, true);
    r.setRequestHeader('Content-Type', 'application/json');
    r.onreadystatechange = makeXhrStateCallback(r,
      function postRetry() { /* TODO */ },
      function postDone(r) {
        if (opt_callback) opt_callback(r);
      });
    r.send(data);
    console.log(url, data);
  }
  exports.xhrpost = xhrpost;
  
  function xhrdelete(url, opt_callback) {
    if (isDown) {
      queuedToRetry['DELETE ' + url] = function() { xhrdelete(url); };
      return;
    }
    var r = new XMLHttpRequest();
    r.open('DELETE', url, true);
    r.onreadystatechange = makeXhrStateCallback(r,
      function delRetry() {
        xhrdelete(url); // causes enqueueing
      },
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
        if (Math.floor(r.status / 100) == 2) {
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
        if (Math.floor(r.status / 100) !== 2) {
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
    
    function transform(json) {
      if (json === null) {
        // occurs when server is paused on load — TODO fix server so it always returns an array
        return fft;
      }
      centerFreq = json[0][0];
      sampleRate = json[0][1];
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
      
      return fft;
    }
    
    ReadCell.call(this, url, fft, values.any, transform);
    
    this.getCenterFreq = function() {
      return centerFreq;
    };
    this.getSampleRate = function() {
      return sampleRate;
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
    var secure = document.location.scheme === 'http' ? '' : 's';
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