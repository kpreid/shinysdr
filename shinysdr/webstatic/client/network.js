// Copyright 2013, 2014, 2015 Kevin Reid <kpreid@switchb.org>
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
  
  var BulkDataType = values.BulkDataType;
  var Cell = values.Cell;
  var CommandCell = values.CommandCell;
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
    r.open('GET', url, true);
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
    r.send();
  }
  exports.externalGet = externalGet;
  
  function ReadWriteCell(setter, assumed, type) {
    Cell.call(this, type);
    var value = assumed;
    var remoteValue = assumed;
    var inhibitTime = 0;
    var inhibitCount = 0;
    var resetTimeout = undefined;
    this.get = function() { return value; },
    this.set = function(newValue) {
      value = newValue;
      this.n.notify();
      inhibitTime = Date.now() + 1000;  // TODO adjust value to observed latency
      setter(newValue, decAndAccept);
      inhibitCount++;
    };
    this._update = function _update(newValue) {
      remoteValue = newValue;
      // If we don't receive a response promptly from the server, then the old value is more accurate than the value we've sent.
      if (resetTimeout) clearTimeout(resetTimeout);
      resetTimeout = setTimeout(acceptFromNetwork, Math.max(0, inhibitTime - Date.now()));
    };
    var decAndAccept = function decAndAccept() {
      // If there are now no outstanding set requests, then the last value we got is the correct valu.
      inhibitCount--;
      if (inhibitCount == 0) {
        acceptFromNetwork();
      }
    };
    var acceptFromNetwork = function acceptFromNetwork() {
      value = remoteValue;
      this.n.notify();
    }.bind(this);
  }
  ReadWriteCell.prototype = Object.create(Cell.prototype, {constructor: {value: ReadWriteCell}});
  exports.ReadWriteCell = ReadWriteCell;
  
  function ReadCell(setter, /* initial */ value, type, transform) {
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
  
  function RemoteCommandCell(setter, type) {
    // TODO: type is kind of useless, make it useful or make it explicitly stubbed out
    function setterAdapter(callback) {
      setter(null, callback);
    }
    CommandCell.call(this, setterAdapter, type);
  }
  RemoteCommandCell.prototype = Object.create(CommandCell.prototype, {constructor: {value: RemoteCommandCell}});
  //exports.CommandCell = CommandCell;  // not yet needed, params in flux, so not exported yet
  
  function BulkDataCell(setter, type) {
    var fft = new Float32Array(1);
    fft[0] = -1e50;
    var VSIZE = Float32Array.BYTES_PER_ELEMENT;
    var lastValue = [{freq:0, rate:1}, fft];

    // kludge to ensure that widgets get all of the frames
    // TODO: put this on a more general and sound framework
    var subscriptions = [];
    
    // infoAndFFT is of the format [{freq:<number>, rate:<number>}, <Float32Array>]
    function transform(buffer) {
      var newValue;
      var view = new DataView(buffer);
      // starts at 4 due to cell-ID field
      switch (type.dataFormat) {
        case 'spectrum-byte':
          var freq = view.getFloat64(4, true);
          var rate = view.getFloat32(4+8, true);
          var offset = view.getFloat32(4+8+4, true);
          var packed_data = new Int8Array(buffer, 4+8+4+4);
          var unpacked_data = new Float32Array(packed_data.length);
          for (var i = packed_data.length - 1; i >= 0; i--) {
            unpacked_data[i] = packed_data[i] - offset;
          }
          //console.log(id, freq, rate, data.length);
          newValue = [{freq:freq, rate:rate}, unpacked_data];
          break;
        case 'scope-float':
          var rate = view.getFloat64(4+8, true);
          var data = new Float32Array(buffer, 4+8);
          newValue = [{rate:rate}, data];
          break;
        default:
          throw new Error('Unknown bulk data format');
      }

      // Deliver value
      lastValue = newValue;
      // TODO replace this with something async
      for (var i = 0; i < subscriptions.length; i++) {
        (0,subscriptions[i])(newValue);
      }
      
      return newValue;
    }
    
    ReadCell.call(this, setter, lastValue, type, transform);
    
    this.subscribe = function(callback) {
      // TODO need to provide for unsubscribing
      subscriptions.push(callback);
      callback(lastValue);
    };
  }
  BulkDataCell.prototype = Object.create(ReadCell.prototype, {constructor: {value: BulkDataCell}});
  exports.BulkDataCell = BulkDataCell;
  
  function setNonEnum(o, p, v) {
    Object.defineProperty(o, p, {
      value: v,
      configurable: true
    })
  }
  
  // use same hostname and path as document, but WS instead of HTTP
  function convertToWebSocketURL(path) {
    // TODO needs to be more robust
    var hostRelPath = /^\//.test(path) ? path : document.location.pathname.replace(/\/$/, '') + '/' + path;
    var secure = document.location.protocol === 'http:' ? '' : 's';
    return 'ws' + secure + '://' + document.location.hostname + ':' + (parseInt(document.location.port) + 1) + hostRelPath;
  }
  exports.convertToWebSocketURL = convertToWebSocketURL;
  
  function openWebSocket(wsURL) {
    // TODO: Have server deliver websocket URL, remove port number requirement
    var ws = new WebSocket(wsURL);
    ws.addEventListener('open', function (event) {
      ws.send(''); // dummy required due to server limitation
    }, true);
    return ws;
  }
  
  var minRetryTime = 1000;
  var maxRetryTime = 20000;
  var backoff = 1.05;
  function retryingConnection(wsURL, connectionStateCallback, callback) {
    if (!connectionStateCallback) connectionStateCallback = function () {};

    var timeout = minRetryTime;
    var succeeded = false;
    function go() {
      var ws = openWebSocket(wsURL);
      ws.addEventListener('open', function (event) {
        succeeded = true;
        timeout = minRetryTime;
        connectionStateCallback('connected');
      }, true);
      ws.addEventListener('close', function (event) {
        if (succeeded) {
          console.error('Lost WebSocket connection', wsURL, '- reason given:', event.reason);
          connectionStateCallback('disconnected');
        } else {
          timeout = Math.min(maxRetryTime, timeout * backoff);
          connectionStateCallback('failed-connect');
        }
        succeeded = false;
        setTimeout(go, timeout);
      }, true);
      callback(ws);
    }
    go();
  };
  exports.retryingConnection = retryingConnection;
  
  function makeBlock(url, interfaces) {
    // TODO convert block operations to use state stream too
    var block = {};
    // TODO kludges, should be properly facetized and separately namespaced somehow
    setNonEnum(block, '_url', url);
    setNonEnum(block, '_reshapeNotice', new events.Notifier());
    interfaces.forEach(function(interfaceName) {
      // TODO: kludge
      setNonEnum(block, '_implements_' + interfaceName, true);
    });
    if (block['_implements_shinysdr.values.IWritableCollection']) {
      setNonEnum(block, 'create', function(desc) {
        // TODO arrange a callback with the resulting _object_
        xhrpost(url, JSON.stringify(desc));
      });
      setNonEnum(block, 'delete', function(key) {
        xhrdelete(url + '/' + encodeURIComponent(key));
      });
    }
    return block;
  }
  
  // TODO: too many args, figure out an object that is a sensible bundle
  function makeCell(url, setter, id, desc, idMap) {
    var cell;
    var type = desc.kind === 'block' ? values.block : typeFromDesc(desc.type);
    if (type instanceof BulkDataType) {
      // TODO can we eliminate this special case
      cell = new BulkDataCell(setter, type);
    } else if (desc.kind === 'block') {
      // TODO eliminate special case by making server block cells less special?
      // TODO blocks should not need urls (switch http op to websocket)
      cell = new ReadCell(setter, /* dummy */ makeBlock(url, []), type,
        function (id) { return idMap[id]; });
    } else if (desc.kind === 'command') {
      cell = new RemoteCommandCell(setter, type);
    } else if (desc.writable) {
      cell = new ReadWriteCell(setter, desc.current, type);
    } else {
      cell = new ReadCell(setter, desc.current, type, identity);
    }
    return [cell, cell._update];
  }
  
  // connectionStateCallback is an optional function of 2 arguments, the first being a enum-ish string identifying the state/problem/notice and the second being details.
  function connect(rootURL, connectionStateCallback) {
    if (!connectionStateCallback) connectionStateCallback = function () {};
    
    var rootCell = new ReadCell(null, null, values.block, identity);
    
    // TODO: URL contents are no longer actually used. URL should be used to derive state stream URL
    //externalGet(rootURL, 'text', function(text) { ... });

    retryingConnection(rootURL, connectionStateCallback, function(ws) {
      ws.binaryType = 'arraybuffer';

      // indexed by object ids chosen by server
      var idMap = Object.create(null);
      var updaterMap = Object.create(null);
      var isCellMap = Object.create(null);
      
      var callbackMap = Object.create(null);
      var nextCallbackId = 0;
      
      idMap[0] = rootCell;
      updaterMap[0] = function (id) { rootCell._update(idMap[id]); };
      isCellMap[0] = true;
      
      function oneMessage(message) {
        var op = message[0];
        var id = message[1];
        switch (message[0]) {
          case 'register_block':
            var url = message[2];
            var interfaces = message[3];
            updaterMap[id] = idMap[id] = makeBlock(url, interfaces);
            isCellMap[id] = false;
            break;
          case 'register_cell':
            var url = message[2];
            var desc = message[3];
            var pair = (function () {
              function setter(value, callback) {
                var cbid = nextCallbackId++;
                callbackMap[cbid] = callback;
                ws.send(JSON.stringify(['set', id, value, cbid]));
              }
              return makeCell(url, setter, id, desc, idMap);
            }());
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
          case 'done':
            callbackMap[id]();
            delete callbackMap[id];
            break;
          default:
            console.error('unknown state stream message', message);
        }
      }
      
      function oneBinaryMessage(buffer) {
        // Currently, BulkDataCell updates are the only type of binary messages.
        var view = new DataView(buffer);
        var id = view.getUint32(0, true);
        var cell_updater = updaterMap[id];
        cell_updater(buffer);
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

    return rootCell;
  }
  exports.connect = connect;
  
  return Object.freeze(exports);
});