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

define(['/test/jasmine-glue.js', '/test/testutil.js',
        'events', 'types', 'values'],
       ( jasmineGlue, testutil,
         events,   types,   values) => {
  'use strict';
  
  const {beforeEach, describe, expect, it} = jasmineGlue.ji;
  const {newListener} = testutil;
  const Notifier = events.Notifier;
  const Scheduler = events.Scheduler;
  
  describe('values', function () {
    let s;
    beforeEach(function () {
      s = new Scheduler(window);
    });
  
    describe('LocalCell', function () {
      it('should not notify immediately after its creation', done => {
        const cell = new values.LocalCell(types.any, 'foo');
        const l = newListener(s);
        cell.n.listen(l);
        l.expectNotCalled(done);
      });
    });
  
    describe('StorageCell', () => {
      // TODO: break up this into individual tests
      beforeEach(() => {
        // TODO: use a mock storage instead of abusing sessionStorage
        sessionStorage.clear();
      });

      it('should function as a cell', done => {
        const ns = new values.StorageNamespace(sessionStorage, 'foo.');
        const cell = new values.StorageCell(ns, String, 'default', 'bar');
        expect(cell.get()).toBe('default');
        cell.set('a');
        expect(cell.get()).toBe('a');
        expect(ns.getItem('bar')).toBe('"a"');
        const l = newListener(s);
        cell.n.listen(l);
        l.expectCalled(() => {
          cell.set('b');
          expect(cell.get()).toBe('b');
        }, done);
      });
    
      function fireStorageEvent() {
        const event = document.createEvent('Event');
        event.initEvent('storage', false, false);
        window.dispatchEvent(event);
      }
    
      it('should notify if a storage event occurs', done => {
        const ns = new values.StorageNamespace(sessionStorage, 'foo.');
        const cell = new values.StorageCell(ns, String, 'default', 'bar');
        const l = newListener(s);
        cell.n.listen(l);
      
        sessionStorage.setItem('foo.bar', '"sval"');
        l.expectCalled(() => {
          fireStorageEvent();
        }, () => {
          expect(cell.get()).toBe('sval');
          done();
        });
      });
    
      it('should not notify if an unrelated storage event occurs', done => {
        const ns = new values.StorageNamespace(sessionStorage, 'foo.');
        const cell = new values.StorageCell(ns, String, 'default', 'bar');
        const l = newListener(s);
        cell.n.listen(l);
      
        sessionStorage.setItem('unrelated', '"sval"');
        fireStorageEvent();
        l.expectNotCalled(() => {
          expect(cell.get()).toBe('default');
          done();
        });
      });
    
      it('should tolerate garbage found in storage', function () {
        sessionStorage.setItem('foo.bar', '}Non-JSON for testing');
        const ns = new values.StorageNamespace(sessionStorage, 'foo.');
        const cell = new values.StorageCell(ns, String, 'default', 'bar');
        expect(cell.get()).toBe('default');
      });
    });
  
    describe('DerivedCell', function () {
      let base, f, calls;
      beforeEach(function () {
        base = new values.LocalCell(types.any, 1);
        calls = 0;
        f = new values.DerivedCell(types.any, s, function (dirty) {
          calls++;
          return base.depend(dirty) + 1;
        });
      });
    
      it('should return a computed value', function () {
        expect(f.get()).toEqual(2);
      });
    
      it('should return an immediately updated value', function () {
        base.set(10);
        expect(f.get()).toEqual(11);
      });
    
      it('should notify and update when the base value is updated', done => {
        const l = newListener(s);
        f.n.listen(l);
        l.expectCalled(() => {
          base.set(10);
        }, () => {
          expect(f.get()).toEqual(11);
          done();
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
      let structure;
      beforeEach(function () {
        structure = new values.LocalCell(types.block, values.makeBlock({
          foo: new values.LocalCell(types.block, values.makeBlock({})),
          bar: new values.LocalCell(types.block, values.makeBlock({}))
        }));
        Object.defineProperty(structure.get().foo.get(), '_implements_Foo', {value:true});
      });
    
      it('should index a block', () => {
        const index = new values.Index(s, structure);
        const results = index.implementing('Foo').get();
        expect(results).toContain(structure.get().foo.get());
        expect(results.length).toBe(1);
      
        const noresults = index.implementing('Bar').get();
        expect(noresults.length).toBe(0);
      });
    
      it('should index a new block', done => {
        const index = new values.Index(s, structure);
        const resultsCell = index.implementing('Bar');
        const l = newListener(s);
        resultsCell.n.listen(l);
        
        const newObj = values.makeBlock({});
        Object.defineProperty(newObj, '_implements_Bar', {value:true});
        
        l.expectCalled(() => {
          structure.get().bar.set(newObj);
        }, () => {
          expect(resultsCell.get().length).toBe(1);
          expect(resultsCell.get()).toContain(newObj);
          
          expect(index.implementing('Foo').get().length).toBe(1);
          
          done();
        });
      });
    
      it('should forget an old block', done => {
        const index = new values.Index(s, structure);
        const resultsCell = index.implementing('Foo');
        const l = newListener(s);
        resultsCell.n.listen(l);
        l.expectCalled(() => {
          structure.get().foo.set(values.makeBlock({}));
        }, () => {
          expect(resultsCell.get().length).toBe(0);
          done();
        });
      });
    
      it('should forget an old cell', done => {
        const dynamic = {
          foo: structure.get().foo
        };
        Object.defineProperty(dynamic, '_reshapeNotice', {value: new Notifier()});
      
        const index = new values.Index(s, new values.LocalCell(types.block, dynamic));
        const resultsCell = index.implementing('Foo');
        const l = newListener(s);
        resultsCell.n.listen(l);
      
        l.expectCalled(() => {
          delete dynamic['foo'];
          dynamic._reshapeNotice.notify();
        }, () => {
          expect(resultsCell.get().length).toBe(0);
          done();
        });
      });
    });
  });
  
  return 'ok';
});