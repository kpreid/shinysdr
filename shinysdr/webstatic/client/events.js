define(function () {
  'use strict';
  
  var exports = {};
  
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
  exports.Scheduler = Scheduler;
  
  function nSchedule(fn) {
    //console.log('Notifier scheduling ' + fn.toString().split('\n')[0]);
    fn.scheduler.enqueue(fn);
  }
  function Notifier() {
    this._listening = [];
  }
  Notifier.prototype.notify = function () {
    this._listening.forEach(nSchedule, this);
    this._listening.length = 0;
  };
  Notifier.prototype.listen = function (fn) {
    if (typeof fn !== 'function') {
      throw new Error('listen called with non-function ' + fn);
    }
    if (typeof fn.scheduler === 'undefined') {
      throw new Error('listen function without scheduler ' + fn);
    }
    this._listening.push(fn);
  };
  exports.Notifier = Notifier;
  
  // Like a Notifier, but doesn't accumulate listeners and never invokes them.
  function Neverfier() {}
  Neverfier.prototype.notify = function () {
    throw new Error('Neverfier.prototype.notify should not be called');
  };
  Neverfier.prototype.listen = function (fn) {
    if (typeof fn !== 'function') {
      throw new Error('listen called with non-function ' + fn);
    }
    if (typeof fn.scheduler === 'undefined') {
      throw new Error('listen function without scheduler ' + fn);
    }
    // do nothing
  };
  exports.Neverfier = Neverfier;
  
  return Object.freeze(exports);
});
