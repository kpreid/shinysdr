var sdr = sdr || {};
(function () {
  'use strict';
  
  var network = sdr.network = {};
  
  // Connectivity management
  var isDown = false;
  var queuedToRetry = Object.create(null);
  var isDownCheckXHR = new XMLHttpRequest();
  var isDownCheckInterval;
  var resyncHooks = [];
  isDownCheckXHR.onreadystatechange = function() {
    if (isDownCheckXHR.readyState === 4) {
      if (isDownCheckXHR.status > 0 && isDownCheckXHR.status < 500) {
        isDown = false;
        clearInterval(isDownCheckInterval);
        resyncHooks.forEach(function (f) { f(); });
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
  network.addResyncHook = function (f) {
    resyncHooks.push(f);
  }
  
  function makeXhrStateCallback(r, retry, whenReady) {
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
        if (Math.floor(r.status / 100) == 2) {
          whenReady();
        } else {
          console.log('XHR was not OK: ' + r.status);
        }
      }
    };
  }
  
  function xhrput(url, data) {
    if (isDown) {
      queuedToRetry['PUT ' + url] = function() { xhrput(url, data); };
      return;
    }
    var r = new XMLHttpRequest();
    r.open('PUT', url, true);
    r.setRequestHeader('Content-Type', 'text/plain');
    r.onreadystatechange = makeXhrStateCallback(r,
      function putRetry() {
        xhrput(url, data); // causes enqueueing
      },
      function () {});
    r.send(data);
    console.log(url, data);
  }
  network.xhrput = xhrput;
  
  function makeXhrGetter(url, callback, binary) {
    var r = new XMLHttpRequest();
    if (binary) r.responseType = 'arraybuffer';
    var self = {
      go: function() {
        if (isDown) {
          queuedToRetry['GET ' + url] = self.go;
          return;
        }
        r.open('GET', url, true);
        r.send();
      }
    };
    r.onreadystatechange = makeXhrStateCallback(r,
      self.go,
      function () {
        callback(binary ? r.response : r.responseText, r);
      });
    return self;
  }
  network.makeXhrGetter = makeXhrGetter;
  
  // unlike makeXhrGetter, doesn't trigger isDown logic, not configured for polling
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
  network.externalGet = externalGet;
  
  Object.freeze(network);
}());