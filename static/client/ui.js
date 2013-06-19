(function () {
  'use strict';
  
  var xhrput = sdr.network.xhrput;
  
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
  
  var scheduler = new sdr.events.Scheduler();
  
  var freqDB = new sdr.database.Union();
  freqDB.add(sdr.database.allSystematic);
  freqDB.add(sdr.database.fromCatalog('/dbs/'));
  
  // Persist state of all IDed 'details' elements
  Array.prototype.forEach.call(document.querySelectorAll('details[id]'), function (details) {
    var ns = new StorageNamespace(localStorage, 'sdr.elementState.' + details.id + '.');
    var stored = ns.getItem('detailsOpen');
    if (stored !== null) details.open = JSON.parse(stored);
    new MutationObserver(function(mutations) {
      ns.setItem('detailsOpen', JSON.stringify(details.open));
    }).observe(details, {attributes: true, attributeFilter: ['open']});
  });
  
  var radio;
  sdr.network.connect('/radio', function gotDesc(remote) {
    radio = remote;

    // Takes center freq as parameter so it can be used on hypotheticals and so on.
    function frequencyInRange(candidate, centerFreq) {
      var halfBandwidth = radio.input_rate.get() / 2;
      if (candidate < halfBandwidth && centerFreq === 0) {
        // recognize tuning for 0Hz gimmick
        return true;
      }
      var fromCenter = Math.abs(candidate - centerFreq) / halfBandwidth;
      return fromCenter > 0.01 && // DC peak
             fromCenter < 0.85;  // loss at edges
    }

    // Kludge to let frequency preset widgets do their thing
    radio.preset = {
      set: function(freqRecord) {
        var freq = freqRecord.freq;
        radio.mode.set(freqRecord.mode);
        if (!frequencyInRange(freq, radio.hw_freq.get())) {
          if (freq < radio.input_rate.get() / 2) {
            // recognize tuning for 0Hz gimmick
            radio.hw_freq.set(0);
          } else {
            //radio.hw_freq.set(freq - 0.2e6);
            // left side, just inside of frequencyInRange's test
            radio.hw_freq.set(freq + radio.input_rate.get() * 0.374);
          }
        }
        radio.receiver.rec_freq.set(freq);
      }
    };
  
    // TODO better structure / move to server
    var _scanView = freqDB;
    radio.scan_presets = new sdr.network.Cell();
    radio.scan_presets.get = function () { return _scanView; };
    radio.scan_presets.set = function (view) {
      _scanView = view;
      this.n.notify();
    };
  
    var view = new sdr.widget.SpectrumView({
      scheduler: scheduler,
      radio: radio,
      element: document.querySelector('.hscalegroup') // TODO relic
    });
  
    function createWidgetsList(rootTarget, list) {
      Array.prototype.forEach.call(list, function (child) {
        createWidgets(rootTarget, child);
      });
    }
    function createWidgets(rootTarget, node) {
      if (node.hasAttribute && node.hasAttribute('data-widget')) {
        var stateObj;
        var typename = node.getAttribute('data-widget');
        var T = sdr.widgets[typename];
        if (!T) {
          console.error('Bad widget type:', node);
          return;
        }
        var stateObj;
        if (node.hasAttribute('data-target')) {
          var targetStr = node.getAttribute('data-target');
          stateObj = rootTarget[targetStr];
          if (!stateObj) {
            node.parentNode.replaceChild(document.createTextNode('[Missing: ' + targetStr + ']'), node);
            return;
          }
        }
        var widget = new T({
          scheduler: scheduler,
          target: stateObj,
          element: node,
          view: view, // TODO should be context-dependent
          freqDB: freqDB,
          radio: radio, // TODO: remove the need for this
          storage: node.hasAttribute('id') ? new StorageNamespace(localStorage, 'sdr.widgetState.' + node.getAttribute('id') + '.') : null
        });
        node.parentNode.replaceChild(widget.element, node);
        widget.element.className += ' ' + node.className + ' widget-' + typename; // TODO kludge
        
        // allow widgets to embed widgets
        createWidgetsList(stateObj || rootTarget, widget.element.childNodes);
      } else if (node.hasAttribute && node.hasAttribute('data-target')) (function () {
        var html = document.createDocumentFragment();
        while (node.firstChild) html.appendChild(node.firstChild);
        function go() {
          // TODO defend against JS-significant keys
          var target = rootTarget[node.getAttribute('data-target')];
          target._deathNotice.listen(go);
          
          node.textContent = ''; // fast clear
          node.appendChild(html.cloneNode(true));
          createWidgetsList(target, node.childNodes);
        }
        go.scheduler = scheduler;
        go();
      }()); else {
        createWidgetsList(rootTarget, node.childNodes);
      }
    }

    createWidgets(radio, document);
  }); // end gotDesc
}());