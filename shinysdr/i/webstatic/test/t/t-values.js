// Copyright 2013, 2014, 2015, 2016 Kevin Reid <kpreid@switchb.org>
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

describe('values', function () {
  var types = shinysdr.types;
  var values = shinysdr.values;
  
  // TODO: duplicated code w/ other tests; move to a common library somewhere
  var s;
  beforeEach(function () {
    s = new shinysdr.events.Scheduler(window);
  });
  function createListenerSpy() {
    var l = jasmine.createSpy();
    l.scheduler = s;
    return l;
  }
  function expectNotification(l) {
    // TODO: we could make a timeless test by mocking the scheduler
    waitsFor(function() {
      return l.calls.length;
    }, 'notification received', 100);
    runs(function() {
      expect(l).toHaveBeenCalledWith();
    });
  }
  function waitsForNotificationCycle() {
    var dummyWait = createListenerSpy();
    s.enqueue(dummyWait);
    expectNotification(dummyWait);
  }
  
  describe('LocalCell', function () {
    it('should not notify immediately after its creation', function () {
      var cell = new values.LocalCell(types.any, 'foo');
      var l = createListenerSpy();
      cell.n.listen(l);
      waitsForNotificationCycle();
      runs(function () {
        expect(l).not.toHaveBeenCalled();
      });
    });
  });
  
  describe('StorageCell', function () {
    // TODO: break up this into individual tests
    beforeEach(function () {
      // TODO: use a mock storage instead of abusing sessionStorage
      sessionStorage.clear();
    })

    it('should function as a cell', function () {
      const ns = new values.StorageNamespace(sessionStorage, 'foo.');
      const cell = new values.StorageCell(ns, String, 'default', 'bar');
      expect(cell.get()).toBe('default');
      cell.set('a');
      expect(cell.get()).toBe('a');
      expect(ns.getItem('bar')).toBe('"a"');
      const l = createListenerSpy();
      cell.n.listen(l);
      cell.set('b');
      expect(cell.get()).toBe('b');
      expectNotification(l);
    });
    
    function fireStorageEvent() {
      const event = document.createEvent('Event');
      event.initEvent('storage', false, false);
      window.dispatchEvent(event);
    }
    
    it('should notify if a storage event occurs', function () {
      const ns = new values.StorageNamespace(sessionStorage, 'foo.');
      const cell = new values.StorageCell(ns, String, 'default', 'bar');
      const l = createListenerSpy();
      cell.n.listen(l);
      
      sessionStorage.setItem('foo.bar', '"sval"');
      fireStorageEvent();
      expectNotification(l);
      expect(cell.get()).toBe('sval');
    });
    
    it('should not notify if an unrelated storage event occurs', function () {
      const ns = new values.StorageNamespace(sessionStorage, 'foo.');
      const cell = new values.StorageCell(ns, String, 'default', 'bar');
      const l = createListenerSpy();
      cell.n.listen(l);
      
      sessionStorage.setItem('unrelated', '"sval"');
      fireStorageEvent();
      waitsForNotificationCycle();
      runs(function () {
        expect(l).not.toHaveBeenCalled();
        expect(cell.get()).toBe('default');
      });
    });
    
    it('should tolerate garbage found in storage', function () {
      sessionStorage.setItem('foo.bar', '}');
      const ns = new values.StorageNamespace(sessionStorage, 'foo.');
      const cell = new values.StorageCell(ns, String, 'default', 'bar');
      expect(cell.get()).toBe('default');
    });
  });
  
  describe('DerivedCell', function () {
    var base, f, calls;
    beforeEach(function () {
      base = new values.LocalCell(types.any, 1);
      calls = 0;
      f = new values.DerivedCell(types.any, s, function (dirty) {
        calls++;
        return base.depend(dirty) + 1;
      });
    })
    
    it('should return a computed value', function () {
      expect(f.get()).toEqual(2);
    });
    
    it('should return an immediately updated value', function () {
      base.set(10);
      expect(f.get()).toEqual(11);
    });
    
    it('should notify and update when the base value is updated', function () {
      var l = createListenerSpy();
      f.n.listen(l);
      base.set(10);
      expectNotification(l);
      runs(function () {
        expect(f.get()).toEqual(11);
      });
    });
    
    it('should not recompute more than necessary', function () {
      expect(f.get()).toEqual(2);
      expect(f.get()).toEqual(2);
      expect(calls).toEqual(1);
      base.set(10);
      expect(f.get()).toEqual(11);
      expect(f.get()).toEqual(11);
      expect(calls).toEqual(2);
    });
  });
  
  describe('Index', function () {
    var structure;
    beforeEach(function () {
      structure = new values.LocalCell(types.block, values.makeBlock({
        foo: new values.LocalCell(types.block, values.makeBlock({})),
        bar: new values.LocalCell(types.block, values.makeBlock({}))
      }));
      Object.defineProperty(structure.get().foo.get(), '_implements_Foo', {value:true});
    });
    
    it('should index a block', function () {
      var index = new values.Index(s, structure);
      var results = index.implementing('Foo').get();
      expect(results).toContain(structure.get().foo.get());
      expect(results.length).toBe(1);
      
      var noresults = index.implementing('Bar').get();
      expect(noresults.length).toBe(0);
    });
    
    it('should index a new block', function () {
      var index = new values.Index(s, structure);
      var resultsCell = index.implementing('Bar');
      var l = createListenerSpy();
      resultsCell.n.listen(l);
      
      var newObj = values.makeBlock({});
      Object.defineProperty(newObj, '_implements_Bar', {value:true});
      structure.get().bar.set(newObj);
      
      expectNotification(l);
      runs(function () {
        expect(resultsCell.get().length).toBe(1);
        expect(resultsCell.get()).toContain(newObj);

        expect(index.implementing('Foo').get().length).toBe(1);
      });
    });
    
    it('should forget an old block', function () {
      var index = new values.Index(s, structure);
      var resultsCell = index.implementing('Foo');
      var l = createListenerSpy();
      resultsCell.n.listen(l);
      
      structure.get().foo.set(values.makeBlock({}));
      
      expectNotification(l);
      runs(function () {
        expect(resultsCell.get().length).toBe(0);
      })
    });
    
    it('should forget an old cell', function () {
      var dynamic = {
        foo: structure.get().foo
      };
      Object.defineProperty(dynamic, '_reshapeNotice', {value: new shinysdr.events.Notifier()});
      
      var index = new values.Index(s, new values.LocalCell(types.block, dynamic));
      var resultsCell = index.implementing('Foo');
      var l = createListenerSpy();
      resultsCell.n.listen(l);
      
      delete dynamic['foo'];
      dynamic._reshapeNotice.notify();
      
      expectNotification(l);
      runs(function () {
        expect(resultsCell.get().length).toBe(0);
      })
    });
  });
});

testScriptFinished();
