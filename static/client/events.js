var sdr = sdr || {};
(function () {
  'use strict';
  
  var events = sdr.events = {};
  
  function schedulerRAFCallback() {
    var limit = 10;
    while (this._queue.length > 0 && limit-- > 0) {
      var queue = this._queue;
      this._queue = [];
      queue.forEach(function (queued) {
        queued._scheduler_scheduled = false;
        queued();
      });
    }
  }
  
  function Scheduler(window) {
    this._queue = [];
    this._callback = schedulerRAFCallback.bind(this);
  }
  Scheduler.prototype.enqueue = function (callback) {
    if (callback._scheduler_scheduled) return;
    this._queue.push(callback);
    callback._scheduler_scheduled = true;  // TODO: use a WeakMap instead
    if (this._queue.length === 1) { // just became nonempty
      window.webkitRequestAnimationFrame(this._callback);
    }
  }
  events.Scheduler = Scheduler;
  
  function nSchedule(listener) {
    this._scheduler.enqueue(listener);
  }
  function Notifier(scheduler) {
    if (typeof scheduler !== 'object') {
      throw new Error('Notifier() without scheduler ' + scheduler);
    }
    var self = this;
    this._scheduler = scheduler;
    this._listening = [];
  }
  Notifier.prototype.notify = function() {
    this._listening.forEach(nSchedule, this);
    this._listening.length = 0;
  };
  Notifier.prototype.listen = function(fn) {
    if (typeof fn !== 'function') {
      throw new Error('listen called with non-function ' + fn);
    }
    this._listening.push(fn);
  };
  events.Notifier = Notifier;
}());