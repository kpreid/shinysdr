// Copyright 2013 Kevin Reid <kpreid@switchb.org>
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
  
  // little abstraction to make the scheduler simpler
  function Queue() {
    this.in = [];
    this.out = [];
  }
  Queue.prototype.enqueue = function (value) {
    this.in.push(value);
  };
  Queue.prototype.nonempty = function () {
    return this.in.length > 0 || this.out.length > 0;
  };
  Queue.prototype.dequeue = function () {
    var inArray = this.in, outArray = this.out;
    if (outArray.length > 0) {
      return outArray.pop();
    } else if (inArray.length > 0) {
      inArray.reverse();
      this.out = inArray;
      this.in = outArray;
      return inArray.pop();
    } else {
      throw new Error('empty queue');
    }
  };
  
  // internal function of Scheduler
  function schedulerRAFCallback() {
    try {
      var limit = 1000;
      var queue = this._queue;
      while (queue.nonempty() && limit-- > 0) {
        var queued = queue.dequeue();
        queued._scheduler_scheduled = false;
        queued();
      }
    } finally {
      if (queue.nonempty()) {
        window.requestAnimationFrame(this._callback);
      } else {
        this._queue_scheduled = false;
      }
    }
  }
  
  function Scheduler(window) {
    // Things to do in the next requestAnimationFrame callback
    this._queue = new Queue();
    // Whether we have an outstanding requestAnimationFrame callback
    this._queue_scheduled = false;
    this._callback = schedulerRAFCallback.bind(this);
  }
  Scheduler.prototype.enqueue = function (callback) {
    if (callback._scheduler_scheduled) return;
    var wasNonempty = this._queue.nonempty();
    this._queue.enqueue(callback);
    callback._scheduler_scheduled = true;  // TODO: use a WeakMap instead once ES6 is out
    if (!wasNonempty && !this._queue_scheduled) { // just became nonempty
      this._queue_scheduled = true;
      window.requestAnimationFrame(this._callback);
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
