(function () {
  function sending(name) {
    return function (obj) { obj[name](); };
  }
  
  var view = {
    fullScale: 10
  };
  
  function SpectrumPlot(buffer, canvas, view) {
    var ctx = canvas.getContext("2d");
    ctx.canvas.width = parseInt(getComputedStyle(canvas).width);
    this.draw = function () {
      var w = ctx.canvas.width;
      var h = ctx.canvas.height;
      var len = buffer.length;
      var scale = ctx.canvas.width / len;
      var yScale = -h / view.fullScale;
      var yZero = h;
      
      ctx.clearRect(0, 0, w, h);
      
      ctx.lineWidth = 0.5;
      ctx.beginPath();
      ctx.moveTo(0, yZero + buffer[0] * yScale);
      for (var i = 1; i < len; i++) {
        ctx.lineTo(i * scale, yZero + buffer[i] * yScale);
      }
      ctx.stroke();
    };
  }
  
  function WaterfallPlot(buffer, canvas, view) {
    canvas.width = buffer.length;
    var ctx = canvas.getContext("2d");
    var ibuf = ctx.createImageData(ctx.canvas.width, 1);
    this.draw = function () {
      var w = ctx.canvas.width;
      var h = ctx.canvas.height;
      var len = buffer.length;
      var scale = len / ctx.canvas.width;
      var colorScale = 255 / view.fullScale;
      
      // scroll
      ctx.drawImage(ctx.canvas, 0, 0, w, h-1, 0, 1, w, h-1);
      
      // new data
      var data = ibuf.data;
      for (var x = 0; x < w; x++) {
        var base = x * 4;
        var intensity = buffer[Math.round(x * scale)] * colorScale;
        data[base] = intensity;
        data[base + 1] = intensity * 2;
        data[base + 2] = intensity * 4;
        data[base + 3] = 255;
      }
      ctx.putImageData(ibuf, 0, 0);
    };
  }
  
  var fft = new Float32Array(2048);
  
  var widgets = [];
  widgets.push(new SpectrumPlot(fft, document.getElementById("spectrum"), view));
  widgets.push(new WaterfallPlot(fft, document.getElementById("waterfall"), view));
  
  function loop() {
    window.webkitRequestAnimationFrame(function() {
      for (var i = fft.length - 1; i >= 0; i--) {
        fft[i] = 2 + Math.log(1 + Math.random() * 4) + 3 * Math.exp(-Math.pow(i - 512, 2) / 100);
      }
      widgets.forEach(sending("draw"));
      loop();
    });
  }
  loop();
}());