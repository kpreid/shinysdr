// Copyright 2014, 2015, 2016 Kevin Reid and the ShinySDR contributors
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

'use strict';

define([
  'events',
  'map/map-core',
  'types',
  'values',
  'widgets',
  'widgets/basic',
  'text!plugins/shinysdr.plugins.aprs/symbol-index',
], (
  import_events,
  import_map_core,
  import_types,
  import_values,
  widgets,
  import_widgets_basic,
  symbolIndexJsonText
) => {
  const {
    Clock,
  } = import_events;
  const {
    register,
    renderTrackFeature,
  } = import_map_core;
  const {
    anyT,
  } = import_types;
  const {
    DerivedCell,
    dependOnPromise,
  } = import_values;
  const {
    Block,
  } = import_widgets_basic;
  
  const symbolIndex = JSON.parse(symbolIndexJsonText);
  
  const exports = {};

  const UNKNOWN_SYMBOL = {description: ''};
  
  function APRSStationWidget(config) {
    Block.call(this, config, function (block, addWidget, ignore, setInsertion, setToDetails, getAppend) {
      ignore('address'); // in header
      addWidget('track', widgets.TrackWidget);
      
      ignore('symbol');
      const symbolCell = block.symbol;
      addWidget(new DerivedCell({
        value_type: anyT,
        naming: {
          label: 'Symbol',
          description: '',
          sort_key: 'symbol'
        }
      }, config.scheduler, dirty => {
        const symbol = symbolCell.depend(dirty);
        return symbol + ' ' + (symbolIndex.symbols[symbol] || UNKNOWN_SYMBOL).description;
      }));
    }, false);
  }
  
  // TODO: Better widget-plugin system so we're not modifying should-be-static tables
  widgets['interface:shinysdr.plugins.aprs.IAPRSStation'] = APRSStationWidget;
  
  // 30 minutes, standard maximum APRS net cycle time
  // TODO: Make this configurable, and share this constant between client and server
  const APRS_TIMEOUT_SECONDS = 60 * 30;

  const OPACITY_STEPS = 20;
  
  const opacityClock = new Clock(APRS_TIMEOUT_SECONDS / OPACITY_STEPS);
  const blinkClock = new Clock(1/30);
  
  function addAPRSMapLayer(mapPluginConfig) {
    mapPluginConfig.addLayer('APRS', {
      featuresCell: mapPluginConfig.index.implementing('shinysdr.plugins.aprs.IAPRSStation'),
      featureRenderer: function renderStation(station, dirty) {
        // TODO: Add multiline text rendering and use it
        const text = [
          station.address.depend(dirty),
          (station.status.depend(dirty) || station.last_comment.depend(dirty))
        ].filter(t => t.trim() !== '').join(' • ');
        
        const f = renderTrackFeature(dirty, station.track, text);
        
        const symbol = station.symbol.depend(dirty);
        if (symbol) {
          // TODO: implement overlay symbols
          const tables = dependOnPromise(dirty, null, aprsSymbolTablesPromise);
          if (tables !== null) {
            f.iconURL = tables[symbol[0] == '\\' ? 1 : 0][symbol.charCodeAt(1) - 33];
          }
        }
        
        const now = opacityClock.convertToTimestampSeconds(opacityClock.depend(dirty));
        const age = now - station.last_heard_time.depend(dirty);
        if (age < 1) {
          blinkClock.depend(dirty);  // cause fast updates
          f.opacity = Math.cos(age * 4 * Math.PI) * 0.5 + 0.5;
        } else {
          f.opacity = 1 - age / APRS_TIMEOUT_SECONDS;
        }
        
        return f;
      }
    });
  }
  
  register(addAPRSMapLayer);
  
  function canvasToObjectURLPromise(canvas) {
    return new Promise(resolve => {
      canvas.toBlob(blob => {
        resolve(URL.createObjectURL(blob));
      });
    });
  }
  
  // Given an image element containing an APRS symbol spritesheet, slice it into an array of URLs for individual images.
  function sliceSpritesheetImage(imageEl) {
    const rows = 6;
    const columns = 16;
    const cellWidth = imageEl.width / columns;
    const cellHeight = imageEl.height / rows;

    const canvas = document.createElement('canvas');
    canvas.width = cellWidth;
    canvas.height = cellHeight;
    const ctx = canvas.getContext('2d');
    const sprites = [];
    for (let y = 0; y < rows; y++) {
      for (let x = 0; x < columns; x++) {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.drawImage(imageEl, -x * cellWidth, -y * cellHeight);
        sprites.push(canvasToObjectURLPromise(canvas));
      }
    }
    return Promise.all(sprites);
  }
  
  function sliceSpritesheetUrl(imageURL) {
    return new Promise((resolve, reject) => {
      const imageEl = document.createElement('img');
      imageEl.onload = () => {
        resolve(sliceSpritesheetImage(imageEl));
      };
      imageEl.onerror = reject;
      imageEl.src = imageURL;
    });
  }
  const aprsSymbolTablesPromise = Promise.all([0, 1, 2].map(index => 
    sliceSpritesheetUrl(
      '/client/plugins/shinysdr.plugins.aprs/symbols/aprs-symbols-24-' + index + '%402x.png')));
  
  //function sliceAPRSSpritesheet(symbol) {
  //  const xIndex = 1;
  //  const yIndex = 1;
  //  const svgDoc = sliceSvgText.replace(/\$([XY])/g, match => {
  //    switch (match[1]) {
  //      case 'X': return -24 * xIndex;
  //      case 'Y': return -24 * yIndex;
  //      default: 
  //        return 0;
  //    }
  //  });
  //  return 'data:image/svg,' + encodeURIComponent(symbol);
  //}
  
  return Object.freeze(exports);
});
