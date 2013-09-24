// Note OpenLayers dependency; OpenLayers is not an AMD module
define(function () {
  'use strict';
  
  var exports = {};
  
  function projectedPoint(lat, lon) {
    return new OpenLayers.Geometry.Point(lon, lat).transform('EPSG:4326', 'EPSG:3857');
  }
  exports.projectedPoint = projectedPoint;

  function markerGraphic(s) {
    return {externalGraphic: 'client/openlayers/img/marker' + s + '.png', graphicHeight: 21, graphicWidth: 16};
  }
  exports.markerGraphic = markerGraphic;
  
  function Map(element, scheduler, db, radio) {
    var baseLayer = new OpenLayers.Layer('Blank', {
      isBaseLayer: true
    });
    // var baseLayer = new OpenLayers.Layer.OSM();
    var olm = new OpenLayers.Map(element, {
      projection: 'EPSG:3857',
      layers: [baseLayer],
      center: projectedPoint(37.663576, -122.271652).getBounds().getCenterLonLat(),
      zoom: 9
    });
    
    olm.addControl(new OpenLayers.Control.LayerSwitcher());
    
    var dbLayer = new OpenLayers.Layer.Vector('Database', {
      styleMap: new OpenLayers.StyleMap({'default':{
        label: '${label}',
        
        fontColor: 'black',
        fontSize: '.8em',
        fontFamily: 'sans-serif',
        labelYOffset: 20,
        labelOutlineColor: 'white',
        labelOutlineWidth: 3,
        
        externalGraphic: 'client/openlayers/img/marker-green.png',
        graphicHeight: 21,
        graphicWidth: 16
      }})
    });
    olm.addLayer(dbLayer);
    function updateDBLayer() {
      db.n.listen(updateDBLayer);
      dbLayer.removeAllFeatures();
      db.forEach(function(entry) {
        // TODO: Add geographic bounds query
        if (entry.location) {
          var feature = new OpenLayers.Feature.Vector(
            projectedPoint(entry.location[0], entry.location[1]),
            {label: entry.label});
          dbLayer.addFeatures([feature]);
        }
      });
    }
    updateDBLayer.scheduler = scheduler;
    updateDBLayer();
    
    // No good way to listen for layout updates, so poll
    // TODO: build a generic resize hook that SpectrumView can use too
    setInterval(function() {
      olm.updateSize();
    }, 1000);
    
    // Receiver-derived data
    function addModeLayer(filterMode, prepare) {
      var modeLayer = new OpenLayers.Layer.Vector(filterMode);
      olm.addLayer(modeLayer);

      function updateOnReceivers() {
        //console.log('updateOnReceivers');
        var receivers = radio.receivers;
        receivers._deathNotice.listen(updateOnReceivers);
        receivers._reshapeNotice.listen(updateOnReceivers);  // TODO break loop if map is dead
        modeLayer.removeAllFeatures();
        for (var key in receivers) (function(receiver) {
          var rDead;
          function death() {
            rDead = true;
            //console.log('clearing for receiver death');
            modeLayer.removeFeatures(features);
          }
          death.scheduler = scheduler;
          receiver._deathNotice.listen(death);
          receiver._deathNotice.listen(updateOnReceivers);  // death notice possibly indicates replacement (TODO make it easier to listen for new blocks in general)
          
          var features = [];
          function updateOnReceiver() {
            if (rDead) return;
            var rMode = receiver.mode.depend(updateOnReceiver);  // TODO break loop if map is dead
            receiver.demodulator._deathNotice.listen(updateOnReceiver);  // not necessary, but useful for our clients
            
            if (rMode !== filterMode) return;
            
            //console.log('clearing to rebuild');
            modeLayer.removeFeatures(features);  // clear old state
            features.length = 0;
            
            prepare(receiver,
              function interested() { return !rDead; },
              function addFeature(feature) {
                if (rDead) throw new Error('dead');
                features.push(feature);
                modeLayer.addFeatures(feature);
              },
              function drawFeature(feature) {
                modeLayer.drawFeature(feature);  // TODO verify is in feature set
              });
          }
          updateOnReceiver.scheduler = scheduler;
          updateOnReceiver();
        }(receivers[key]));
      }
      updateOnReceivers.scheduler = scheduler;
      updateOnReceivers();
    }

    plugins.forEach(function(pluginFunc) {
      // TODO provide an actually designed interface
      pluginFunc(db, scheduler, addModeLayer);
    });
  }
  exports.Map = Map;
  
  var plugins = [];
  exports.register = function(pluginFunc) {
    plugins.push(pluginFunc);
  };
  
  return Object.freeze(exports);
});