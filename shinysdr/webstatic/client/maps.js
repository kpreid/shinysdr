// Note OpenLayers dependency; OpenLayers is not an AMD module
define(function () {
  'use strict';
  
  var exports = {};
  
  function Map(element, scheduler, db, radio) {
    function projectedPoint(lat, lon) {
      return new OpenLayers.Geometry.Point(lon, lat).transform('EPSG:4326', 'EPSG:3857');
    }
    
    function markerGraphic(s) {
      return {externalGraphic: 'client/openlayers/img/marker' + s + '.png', graphicHeight: 21, graphicWidth: 16};
    }
    
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

    // TODO this should live in the VOR plugin, once plugins can have client-side functionality
    addModeLayer('VOR', function(receiver, interested, addFeature, drawFeature) {
      var angleCell = receiver.demodulator.angle;  // demodulator change will be handled by addModeLayer
      var freqCell = receiver.rec_freq;
      var lengthInDegrees = 0.5;
      
      var records = db.inBand(freqCell.get(), freqCell.get()).type('channel').getAll();
      var record = records[0];
      if (!record) {
        console.log('VOR map: No record match', freqCell.get());
        return;
      }
      if (!record.location) {
        console.log('VOR map: Record has no location', record.label);
        return;
      }
      var lat = record.location[0];
      var lon = record.location[1];
      // TODO update location if db/record/freq changes
      
      var origin = projectedPoint(lat, lon);
      var lengthProjected = projectedPoint(lat + lengthInDegrees, lon).y - origin.y;
      
      var ray = new OpenLayers.Geometry.LineString([origin]);
      var marker = new OpenLayers.Feature.Vector(origin, {}, markerGraphic('-gold'));
      var rayFeature = new OpenLayers.Feature.Vector(ray, {}, {
        strokeDashstyle: 'dot'
      });
      addFeature(marker);
      addFeature(rayFeature);
      
      var prevEndPoint;
      function update() {
        if (!interested()) return;
        var angle = angleCell.depend(update);
        // TODO: Need to apply an offset of the VOR station's difference from geographic north (which we need to put in the DB)
        var sin = Math.sin(angle);
        // The following assumes that the projection in use is conformal, and that the length is small compared to the curvature.
        var end = new OpenLayers.Geometry.Point(
          origin.x + Math.sin(angle) * lengthProjected,
          origin.y + Math.cos(angle) * lengthProjected);
        ray.addPoint(end);
        if (prevEndPoint) {
          ray.removePoint(prevEndPoint);
        }
        prevEndPoint = end;
        drawFeature(rayFeature);
      }
      update.scheduler = scheduler;
      update();
    });
  }
  exports.Map = Map;
  
  return Object.freeze(exports);
});