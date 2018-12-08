// Copyright 2013, 2014, 2015, 2016 Kevin Reid and the ShinySDR contributors
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

define([
  '/test/jasmine-glue.js',
  '/test/testutil.js',
  'events',
  'types',
  'values',
], (
  import_jasmine,
  import_testutil,
  import_events,
  import_types,
  import_values
) => {
  const {ji: {
    beforeEach,
    describe,
    expect,
    it,
  }} = import_jasmine;
  const {
    newListener
  } = import_testutil;
  const {
    Notifier,
    Scheduler,
  } = import_events;
  const {
    EnumT,
    anyT,
    blockT,
    booleanT,
    numberT,
    stringT,
  } = import_types;
  const {
    ConstantCell,
    DerivedCell,
    findImplementersInBlockCell,
    Index,
    LocalCell,
    StorageCell,
    StorageNamespace,
    dependOnPromise,
    makeBlock,
  } = import_values;
  
  describe('values', function () {
    let s;
    beforeEach(function () {
      s = new Scheduler(window);
    });
    
    describe('ConstantCell', () => {
      it('should infer boolean type', () => {
        expect(new ConstantCell(false).type).toBe(booleanT);
      });
      it('should infer number type', () => {
        expect(new ConstantCell(0).type).toBe(numberT);
      });
      it('should infer string type', () => {
        expect(new ConstantCell('').type).toBe(stringT);
      });
      it('should infer block type', () => {
        expect(new ConstantCell(makeBlock({})).type).toBe(blockT);
      });
      it('should not infer a type for an arbitrary object', () => {
        expect(() => {
          new ConstantCell({});
        }).toThrow();
      });
      it('should use an explicit type', () => {
        const t = new EnumT({'a': 'aa'});
        const cell = new ConstantCell('not-even-in-type', t);
        expect(cell.type).toBe(t);
        expect(cell.get()).toBe('not-even-in-type');
      });
    });
    
    describe('LocalCell', function () {
      it('should not notify immediately after its creation', done => {
        const cell = new LocalCell(anyT, 'foo');
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
        const ns = new StorageNamespace(sessionStorage, 'foo.');
        const cell = new StorageCell(ns, stringT, 'default', 'bar');
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
        const ns = new StorageNamespace(sessionStorage, 'foo.');
        const cell = new StorageCell(ns, stringT, 'default', 'bar');
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
        const ns = new StorageNamespace(sessionStorage, 'foo.');
        const cell = new StorageCell(ns, stringT, 'default', 'bar');
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
        const ns = new StorageNamespace(sessionStorage, 'foo.');
        const cell = new StorageCell(ns, stringT, 'default', 'bar');
        expect(cell.get()).toBe('default');
      });
    });
  
    describe('DerivedCell', function () {
      let base, f, calls;
      beforeEach(function () {
        base = new LocalCell(anyT, 1);
        calls = 0;
        f = new DerivedCell(anyT, s, function (dirty) {
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
  
    describe('dependOnPromise', () => {
      it('eventually returns the value of a resolved promise', done => {
        const l = newListener(s);
        const promise = Promise.resolve('b');
        const call = () => dependOnPromise(l, 'a', promise);
        expect(call()).toBe('a');
        l.expectCalledWhenever(() => {
          expect(call()).toBe('b');
          done();
        });
      });
      it('ignores a rejected promise', done => {
        const l = newListener(s);
        const promise = Promise.reject(new Error('Uncaught for testing dependOnPromise'));
        const call = () => dependOnPromise(l, 'a', promise);
        expect(call()).toBe('a');
        l.expectNotCalled(done);
      });
    });

    describe('findImplementersInBlockCell', () => {
      let structure;
      beforeEach(function () {
        structure = new LocalCell(blockT, makeBlock({
          foo: new LocalCell(blockT, makeBlock({})),
          bar: new LocalCell(blockT, makeBlock({}))
        }));
        Object.defineProperty(structure.get().foo.get(), '_implements_Foo', {value:true});
      });

      it('should find foo', () => {
        const results = findImplementersInBlockCell(s, structure, 'Foo').get();
        expect(results).toContain(structure.get().foo.get());
        expect(results.length).toBe(1);

        const noresults = findImplementersInBlockCell(s, structure, 'Bar').get();
        expect(noresults.length).toBe(0);
      });

      it('should notice when a block starts implementing an interface', () => {
        const block = findImplementersInBlockCell(s, structure, 'Foo');
        expect(block.get().length).toBe(1);
        const newBar = makeBlock({});
        Object.defineProperty(newBar, '_implements_Foo', {value:true});
        structure.get().bar.set(newBar);
        expect(block.get().length).toBe(2);
      });
    });

    describe('Index', function () {
      let structure;
      beforeEach(function () {
        structure = new LocalCell(blockT, makeBlock({
          foo: new LocalCell(blockT, makeBlock({})),
          bar: new LocalCell(blockT, makeBlock({}))
        }));
        Object.defineProperty(structure.get().foo.get(), '_implements_Foo', {value:true});
      });
    
      it('should index a block', () => {
        const index = new Index(s, structure);
        const results = index.implementing('Foo').get();
        expect(results).toContain(structure.get().foo.get());
        expect(results.length).toBe(1);
      
        const noresults = index.implementing('Bar').get();
        expect(noresults.length).toBe(0);
      });
    
      it('should index a new block', done => {
        const index = new Index(s, structure);
        const resultsCell = index.implementing('Bar');
        const l = newListener(s);
        resultsCell.n.listen(l);
        
        const newObj = makeBlock({});
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
        const index = new Index(s, structure);
        const resultsCell = index.implementing('Foo');
        const l = newListener(s);
        resultsCell.n.listen(l);
        l.expectCalled(() => {
          structure.get().foo.set(makeBlock({}));
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
      
        const index = new Index(s, new LocalCell(blockT, dynamic));
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
