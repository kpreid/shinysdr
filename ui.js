(function () {
  function sending(name) {
    return function (obj) { obj[name](); };
  }
  
  function SpectrumPlot(buffer, canvas) {
    var ctx = canvas.getContext("2d");
    ctx.canvas.width = parseInt(getComputedStyle(canvas).width);
    this.draw = function () {
      var w = ctx.canvas.width;
      var h = ctx.canvas.height;
      var len = buffer.length;
      var scale = ctx.canvas.width / len;
      
      ctx.clearRect(0, 0, w, h);
      
      ctx.beginPath();
      for (var i = 0; i < len; i++) {
        ctx[i ? "lineTo" : "moveTo"](i * scale, h / 2 + buffer[i] * (h / 10));
      }
      ctx.stroke();
    };
  }
  
  function WaterfallPlot(buffer, canvas) {
    canvas.width = buffer.length;
    var ctx = canvas.getContext("2d");
    var ibuf = ctx.createImageData(ctx.canvas.width, 1);
    this.draw = function () {
      var w = ctx.canvas.width;
      var h = ctx.canvas.height;
      var len = buffer.length;
      var scale = len / ctx.canvas.width;
      
      // scroll
      ctx.drawImage(ctx.canvas, 0, 0, w, h-1, 0, 1, w, h-1);
      
      // new data
      var data = ibuf.data;
      for (var x = 0; x < w; x++) {
        var base = x * 4;
        data[base] = 128 + buffer[Math.round(x * scale)] * 127;
        data[base + 1] = 255;
        data[base + 2] = 0;
        data[base + 3] = 255;
      }
      ctx.putImageData(ibuf, 0, 0);
    };
  }
  
  var fft = new Float32Array(200);
  
  var widgets = [];
  widgets.push(new SpectrumPlot(fft, document.getElementById("spectrum")));
  widgets.push(new WaterfallPlot(fft, document.getElementById("waterfall")));
  
  function loop() {
    window.webkitRequestAnimationFrame(function() {
      for (var i = fft.length - 1; i >= 0; i--) {
        fft[i] = 2 - Math.log(1 + Math.random() * 4);
      }
      widgets.forEach(sending("draw"));
      loop();
    });
  }
  loop();
}());