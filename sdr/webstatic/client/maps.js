// Note OpenLayers dependency; OpenLayers is not an AMD module
define(function () {
  'use strict';
  
  var exports = {};
  
  function Map(element, scheduler, db) {
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
  }
  exports.Map = Map;
  
  return Object.freeze(exports);
});