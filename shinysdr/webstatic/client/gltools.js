// Copyright 2015 Kevin Reid <kpreid@switchb.org>
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

define(function () {
  'use strict';
  
  var exports = {};
  
  exports.getGL = function getGL(config, canvas, options) {
    var useWebGL = config.clientState.opengl.depend(config.rebuildMe);
    return !useWebGL ? null : canvas.getContext('webgl', options) || canvas.getContext('experimental-webgl', options);
  };
  
  exports.buildProgram = function buildProgram(gl, vertexShaderSource, fragmentShaderSource) {
    function compileShader(type, source) {
      var shader = gl.createShader(type);
      gl.shaderSource(shader, source);
      gl.compileShader(shader);
      if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
        throw new Error(gl.getShaderInfoLog(shader));
      }
      return shader;
    }
    var vertexShader = compileShader(gl.VERTEX_SHADER, vertexShaderSource);
    var fragmentShader = compileShader(gl.FRAGMENT_SHADER, fragmentShaderSource);
    var program = gl.createProgram();
    gl.attachShader(program, vertexShader);
    gl.attachShader(program, fragmentShader);
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
      throw new Error(gl.getProgramInfoLog(program));
    }
    gl.useProgram(program);
    return program;
  };
  
  exports.handleContextLoss = function handleContextLoss(canvas, callback) {
    canvas.addEventListener('webglcontextlost', function (event) {
      event.preventDefault();
    }, false);
    canvas.addEventListener('webglcontextrestored', callback, false);
  };
  
  // Manage a float vertex attribute array and compute the indices.
  // layoutEntries is an array of { name: <shader's attribute name>, components: <integer> }.
  function AttributeLayout(gl, program, layoutEntries) {
    this._gl = gl;
    this._BPE = Float32Array.BYTES_PER_ELEMENT;
    this._elementsPerVertex = 0;
    this.offsets = Object.create(null);
    this._complete = [];
    layoutEntries.forEach(function (entry) {
      var attribLocation = gl.getAttribLocation(program, entry.name);
      if (attribLocation === -1) {
        throw new Error('attribute ' + JSON.stringify(entry.name) + ' is not defined or otherwise invalid');
      }
      
      var offset = this._elementsPerVertex;
      this._elementsPerVertex += entry.components;

      this.offsets[entry.name] = offset;
      this._complete.push({
        attrib: attribLocation,
        components: entry.components,
        byteOffset: offset * this._BPE
      });
    }, this);
    Object.freeze(this.offsets);
    Object.freeze(this);
  };
  AttributeLayout.prototype.elementsPerVertex = function () {
    return this._elementsPerVertex;
  };
  // the relevant buffer should be already bound
  AttributeLayout.prototype.attrib = function () {
    var gl = this._gl;
    var stride = this._elementsPerVertex * this._BPE;
    this._complete.forEach(function (layoutItem) {
      gl.enableVertexAttribArray(layoutItem.attrib);
      gl.vertexAttribPointer(
        layoutItem.attrib,
        layoutItem.components,
        gl.FLOAT,
        false,
        stride,
        layoutItem.byteOffset);
    });
  };
  AttributeLayout.prototype.unattrib = function () {
    var gl = this._gl;
    this._complete.forEach(function (layoutItem) {
      gl.disableVertexAttribArray(layoutItem.attrib);
    }, this);
  };
  exports.AttributeLayout = AttributeLayout;
  
  return Object.freeze(exports);
});
