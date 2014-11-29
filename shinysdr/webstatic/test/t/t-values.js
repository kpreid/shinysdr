// Copyright 2013, 2014 Kevin Reid <kpreid@switchb.org>
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

  describe('Range', function () {
    var Range = values.Range;
    function frange(subranges) {
      return new Range(subranges, false, false);
    }
    it('should round at the ends of simple ranges', function () {
      expect(frange([[1, 3]]).round(0, -1)).toBe(1);
      expect(frange([[1, 3]]).round(2, -1)).toBe(2);
      expect(frange([[1, 3]]).round(4, -1)).toBe(3);
      expect(frange([[1, 3]]).round(0, 1)).toBe(1);
      expect(frange([[1, 3]]).round(2, 1)).toBe(2);
      expect(frange([[1, 3]]).round(4, 1)).toBe(3);
    });
    it('should round in the gaps of split ranges', function () {
      expect(frange([[1, 2], [3, 4]]).round(2.4, 0)).toBe(2);
      expect(frange([[1, 2], [3, 4]]).round(2.4, -1)).toBe(2);
      expect(frange([[1, 2], [3, 4]]).round(2.4, +1)).toBe(3);
      expect(frange([[1, 2], [3, 4]]).round(2.6, -1)).toBe(2);
      expect(frange([[1, 2], [3, 4]]).round(2.6, +1)).toBe(3);
      expect(frange([[1, 2], [3, 4]]).round(2.6, 0)).toBe(3);
    });
    it('should round at the ends of split ranges', function () {
      expect(frange([[1, 2], [3, 4]]).round(0,  0)).toBe(1);
      expect(frange([[1, 2], [3, 4]]).round(0, -1)).toBe(1);
      expect(frange([[1, 2], [3, 4]]).round(0, +1)).toBe(1);
      expect(frange([[1, 2], [3, 4]]).round(5,  0)).toBe(4);
      expect(frange([[1, 2], [3, 4]]).round(5, -1)).toBe(4);
      expect(frange([[1, 2], [3, 4]]).round(5, +1)).toBe(4);
    });
  });
  
  describe('LocalCell', function () {
    it('should not notify immediately after its creation', function () {
      var cell = new values.LocalCell(values.any, 'foo');
      var l = createListenerSpy();
      cell.n.listen(l);
      var dummyWait = createListenerSpy();
      s.enqueue(dummyWait);
      expectNotification(dummyWait);
      runs(function () {
        expect(l).not.toHaveBeenCalled();
      });
    });
  });
  
  describe('StorageCell', function () {
    // TODO: break up this into individual tests
    it('should function as a cell', function () {
      // TODO: use a mock storage instead of abusing sessionStorage
      sessionStorage.clear();
      var ns = new values.StorageNamespace(sessionStorage, 'foo.');
      var cell = new values.StorageCell(ns, 'bar');
      expect(cell.get()).toBe(null);
      cell.set('a');
      expect(cell.get()).toBe('a');
      var l = createListenerSpy();
      cell.n.listen(l);
      cell.set('b');
      expect(cell.get()).toBe('b');
      expectNotification(l);
    });
  });
  
  describe('DerivedCell', function () {
    var base, f, calls;
    beforeEach(function () {
      base = new values.LocalCell(values.any, 1);
      calls = 0;
      f = new values.DerivedCell(values.any, s, function (dirty) {
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
      structure = new values.LocalCell(values.block, values.makeBlock({
        foo: new values.LocalCell(values.block, values.makeBlock({})),
        bar: new values.LocalCell(values.block, values.makeBlock({}))
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
      
      var index = new values.Index(s, new values.LocalCell(values.block, dynamic));
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
