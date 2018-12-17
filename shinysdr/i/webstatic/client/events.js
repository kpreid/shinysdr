// Copyright 2013, 2015, 2016 Kevin Reid and the ShinySDR contributors
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

define(() => {
  const exports = {};
  
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
  
  class AbstractScheduler {
    // All methods of schedulers that can be defined in terms of others.
    
    claim(callback) {
      // TODO: convert this to a common WeakMap
      if (callback.scheduler !== undefined) {
        throw new Error('Already claimed by a different scheduler');
      }
      callback.scheduler = this;
      return callback;  // Allow `return claim(function ...);` pattern.
    }
    
    startNow(callback) {
      this.claim(callback);
      callback();
    }
    
    startLater(callback) {
      this.claim(callback);
      this.enqueue(callback);
    }
    
    enqueue(callback) { throw new Error('not implemented'); }
    callNow(callback) { throw new Error('not implemented'); }
    syncEventCallback(eventCallback) { throw new Error('not implemented'); }
  }
  
  class Scheduler extends AbstractScheduler {
    constructor(window) {
      super();
      const i = new SchedulerImpl(window, this);
      this.enqueue = i.enqueue.bind(i);
      this.callNow = i.callNow.bind(i);
      this.syncEventCallback = i.syncEventCallback.bind(i);
    }
  }
  exports.Scheduler = Scheduler;
  
  class SchedulerImpl {
    constructor(window, scheduler) {
      this._window = window;
      this._scheduler = scheduler;  // caution: scheduler is not yet fully constructed
      
      // Things to do in the next requestAnimationFrame callback
      this._queue = new Queue();
      
      // Whether we have an outstanding requestAnimationFrame callback
      this._queue_scheduled = false;
      
      // Contains every function which is to be called. Every function in the queue either is also in this set or was called early by .callNow().
      this._functionIsScheduled = new Set();
      
      // Bound callback to pass to requestAnimationFrame
      this._callback = this._RAFCallback.bind(this);
    }
    
    enqueue(callback) {
      if (callback.scheduler !== this._scheduler) throw new Error('Wrong scheduler');
      if (this._functionIsScheduled.has(callback)) return;
      var wasNonempty = this._queue.nonempty();
      this._queue.enqueue(callback);
      this._functionIsScheduled.add(callback);
      if (!wasNonempty && !this._queue_scheduled) { // just became nonempty
        this._queue_scheduled = true;
        window.requestAnimationFrame(this._callback);
      }
    }
    
    callNow(callback) {
      if (callback.scheduler !== this._scheduler) throw new Error('Wrong scheduler');
      this._functionIsScheduled.delete(callback);
      // TODO: Revisit whether we should catch errors here
      callback();
    }
    
    // Kludge for when we need the consequences of user interaction to happen promptly (before the event handler returns). Requirement: use this only to wrap 'top level' callbacks called with nothing significant on the stack.
    syncEventCallback(eventCallback) {
      const wrappedForSync = () => {
        // note no error catching -- don't think it needs it
        var value = eventCallback();
        this._callback();
        return value;
      };
      return wrappedForSync;
    }
    
    _RAFCallback() {
      const queue = this._queue;
      let limit = 1000;
      try {
        while (queue.nonempty() && limit-- > 0) {
          const queued = queue.dequeue();
          if (this._functionIsScheduled.has(queued)) {
            this._functionIsScheduled.delete(queued);
            queued();
          }
        }
      } finally {
        if (queue.nonempty()) {
          window.requestAnimationFrame(this._callback);
        } else {
          this._queue_scheduled = false;
        }
      }
    }
  }
  
  class SubScheduler extends AbstractScheduler {
    constructor(superScheduler, disableConditionBinder) {
      super();
      const i = new SubSchedulerImpl(superScheduler, this);
      this.enqueue = i.enqueue.bind(i);
      this.callNow = i.callNow.bind(i);
      this.syncEventCallback = i.syncEventCallback.bind(i);
      disableConditionBinder(i.disableSubScheduler.bind(i));
    }
  }
  exports.SubScheduler = SubScheduler;
  
  class SubSchedulerImpl {
    constructor(superScheduler, scheduler) {
      this._superScheduler = superScheduler;
      this._enabled = true;
      this._wrappers = new WeakMap();
    }
    
    disableSubScheduler() {
      this._enabled = false;
    }
    
    _wrap(callback) {
      let subSchedulerWrapper = this._wrappers.get(callback);
      if (!subSchedulerWrapper) {
        // Note the wrapper's .name is taken from the variable.
        subSchedulerWrapper = () => {
          if (this._enabled) {
            callback();
          }
        };
        this._superScheduler.claim(subSchedulerWrapper);
        this._wrappers.set(callback, subSchedulerWrapper);
      }
      return subSchedulerWrapper;
    }
    
    enqueue(callback) {
      this._superScheduler.enqueue(this._wrap(callback));
    }
    
    callNow(callback) {
      if (this._enabled) {
        this._superScheduler.callNow(this._wrap(callback));
      } else {
        // Call the callback whether-or-not we are disabled.
        // Rationale: Code that does callNow may depend on the side effects of the callback for it to finish successfully.
        callback();
      }
    }
    
    syncEventCallback(eventCallback) {
      return this._superScheduler.syncEventCallback(eventCallback);
    }
  }
  
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
  
  // A source of the current time in SECONDS which:
  //   * works with schedulers/callbacks
  //   * has a slightly coarse granularity of updates
  //   * is offset to be close to zero, to be easier on low-precision math
  function Clock(granularitySeconds) {
    var granularityMs = granularitySeconds * 1000;
    var clockEpoch_ms = Date.now();
    var clockEpoch_s = clockEpoch_ms / 1000;
    
    var clockRunningFor = new Set();
    function enq(f) {
      clockRunningFor.delete(f);
      f.scheduler.enqueue(f);
    }
    function fireClock() {
      clockRunningFor.forEach(enq);
    }
    
    this.depend = function clockDepend(dirtyCallback) {
      var before = clockRunningFor.size;
      clockRunningFor.add(dirtyCallback);
      var after = clockRunningFor.size;
      if (!before && after) {
        setTimeout(fireClock, granularityMs);
      }
      return (Date.now() - clockEpoch_ms) / 1000;
    };
    this.convertFromTimestampSeconds = function (value) {
      return value - clockEpoch_s;
    };
    this.convertToTimestampSeconds = function (value) {
      return value + clockEpoch_s;
    };
  }
  exports.Clock = Clock;
  
  // Utility for turning "this list was updated" into "these items were added and removed".
  // TODO: Doesn't really fit with the rest of this module.
  //
  // handler: object with methods
  //    .add(key) => value
  //    .remove(key, value)
  // where value is helpfully remembered by the AddKeepDrop but not used otherwise.
  //
  // Either do
  //   akd.begin(); for (...) akd.add(key); akd.end()
  // or call update() with an iterable.
  function AddKeepDrop(handler) {
    if (!('add' in handler && 'remove' in handler)) {
      throw new Error('AddKeepDrop: handler methods missing');
    }
    
    const have = new Map();
    const keep = new Set();
    let active = false;
    return {
      begin() {
        if (active) {
          throw new Error('AddKeepDrop: misnested begin');
        }
        keep.clear();
        active = true;
      },
      
      add(key) {
        if (!active) {
          throw new Error('AddKeepDrop: misnested add');
        }
        keep.add(key);
      },
      
      end() {
        if (!active) {
          throw new Error('AddKeepDrop: misnested add');
        }
        active = false;
        have.forEach((value, key) => {
          if (!keep.has(key)) {
            handler.remove(key, value);
            have.delete(key);
          }
        });
        keep.forEach(key => {
          if (!have.has(key)) {
            have.set(key, handler.add(key));
          }
        });
        keep.clear();  // Don't prevent GC of dropped items.
      },
      
      update(iterable) {
        this.begin();
        for (const key of iterable) {
          this.add(key);
        }
        this.end();
      }
    };
  }
  exports.AddKeepDrop = AddKeepDrop;

  return Object.freeze(exports);
});
