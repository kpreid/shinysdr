// Copyright 2013, 2014, 2015 Kevin Reid <kpreid@switchb.org>
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

define(['/test/jasmine-glue.js', '/test/testutil.js',
        'database', 'events'],
       ( jasmineGlue, testutil,
         database,   events) => {
  const {beforeEach, describe, expect, it} = jasmineGlue.ji;
  const {newListener} = testutil;
  const Scheduler = events.Scheduler;
  const Table = database.Table;
  const Union = database.Union;

  describe('database', function () {
    let s;
    beforeEach(function () {
      s = new Scheduler(window);
    });
    
    const dummyRecord = Object.freeze({
      type: 'channel',
      freq: 100e6
    });
  
    describe('Source', function () {
      it('should match band edges correctly', function () {
        const t = new Table('foo', true);
        const r = t.add({lowerFreq: 100, upperFreq: 200});
        // slice is to work around a jasmine bug where it assumes objects are mutable
        expect(t.inBand(0, 90).getAll().slice()).toEqual([]);
        expect(t.inBand(90, 110).getAll().slice()).toEqual([r]);
        expect(t.inBand(110, 190).getAll().slice()).toEqual([r]);
        expect(t.inBand(190, 210).getAll().slice()).toEqual([r]);
        expect(t.inBand(210, 300).getAll().slice()).toEqual([]);
      });
    });
  
    describe('Table', function () {
      it('should notify on record addition', done => {
        const t = new Table('foo', true);
        const l = newListener(s);
        t.n.listen(l);
        l.expectCalled(() => {
          t.add(dummyRecord);
        }, done);
      });
    
      it('should notify on record modification', done => {
        const t = new Table('foo', true);
        const l = newListener(s);
        const r = t.add({
          type: 'channel',
          freq: 100e6
        });
        t.n.listen(l);
        l.expectCalled(() => {
          r.freq = 120e6;
        }, done);
      });

      it('should report writability', function () {
        expect(new Table('writable', true).writable).toBe(true);
        expect(new Table('ro', false).writable).toBe(false);
      });

      it('should refuse to add records if not writable', function () {
        expect(function () {
          new Table('writable', false).add({});
        }).toThrowError('This table is read-only');
      });

      it('should refuse to modify records if not writable', function () {
        const table = new Table('writable', false, function(init) {
          init.add({freq: 0, label: 'foo'});
        });
        expect(table.getAll()[0].writable).toBe(false);
        expect(function () {
          table.getAll()[0].label = 'bar';
        }).toThrowError('This record is read-only');
        expect(table.getAll()[0].label).toBe('foo');
      });
    });
  
    describe('Record', function () {
      it('should have consistent frequency values', function () {
        const r = new Table('foo', true).add({});
        // It is always the case that freq is the midpoint between lowerFreq and upperFreq.
        expect(r.lowerFreq).toBeNaN();
        expect(r.upperFreq).toBeNaN();
        expect(r.freq).toBeNaN();
        r.lowerFreq = 1;
        expect(r.lowerFreq).toBe(1);
        expect(r.upperFreq).toBeNaN();
        expect(r.freq).toBeNaN();
        r.upperFreq = 2;
        expect(r.lowerFreq).toBe(1);
        expect(r.upperFreq).toBe(2);
        expect(r.freq).toBe(1.5);
        r.freq = 3;
        expect(r.lowerFreq).toBe(3);
        expect(r.upperFreq).toBe(3);
        expect(r.freq).toBe(3);
      });
    
      it('should report writability', function () {
        function makeRecord(writable) {
          const table = new Table('writable', false, function (init) {
            if (writable) init.makeWritable();
            init.add({});
          });
          return table.getAll()[0];
        }
        expect(makeRecord(true).writable).toBe(true);
        expect(makeRecord(false).writable).toBe(false);
      });

      it('should notify on record modification', done => {
        const t = new Table('foo', true);
        const l = newListener(s);
        const r = t.add({
          type: 'channel',
          freq: 100e6
        });
        r.n.listen(l);
        l.expectCalled(() => {
          r.freq = 120e6;
        }, done);
      });
    
      it('should have default values', function () {
        const r = (new Table('foo', true)).add({});
        expect(r.writable).toEqual(true);
        expect(r.type).toEqual('channel');
        expect(r.mode).toEqual('?');
        expect(r.freq).toBeNaN();
        expect(r.lowerFreq).toBeNaN();
        expect(r.upperFreq).toBeNaN();
        expect(r.location).toEqual(null);
        expect(r.label).toEqual('');
        expect(r.notes).toEqual('');
      });

      it('should round-trip through JSON', function () {
        const plainRecord = {
          type: 'channel',
          label: 'foo',
          notes: 'bar',
          mode: 'USB',
          lowerFreq: 123.4e6,
          upperFreq: 123.4e6,
          location: null
        };
        // TODO: test location value (not doing so for now because toEqual is apparently not deep)
        const r = (new Table('foo', true)).add(plainRecord);
        expect(r.toJSON()).toEqual(plainRecord);
      });

      it('should coerce a location', function () {
        const r = (new Table('foo', true)).add({location: ['1', '2']});
        expect(r.location.length).toEqual(2);
        expect(r.location[0]).toEqual(1);
        expect(r.location[1]).toEqual(2);
      });

    });

    describe('GroupView', function () {
      let t, r1, r2, view;
      beforeEach(function () {
        t = new Table('foo', true);
        r1 = t.add({type: 'channel', freq: 100e6, label: 'a'});
        r2 = t.add({type: 'channel', freq: 100e6, label: 'b'});
        view = t.groupSameFreq();
      });
    
      it('should return a grouped record', function () {
        expect(view.getAll().length).toBe(1);
        const r = view.getAll()[0];
        expect(typeof r).toBe('object');
        expect(r.type).toBe('group');
        expect(r.freq).toBe(100e6);
        expect(r.grouped.length).toEqual(2);
        expect(r.grouped).toContain(r1);
        expect(r.grouped).toContain(r2);
      });
    
      it('record should not change and have an inert notifier', done => {
        // We don't actually specifically _want_ to have an immutable group record, but we're testing the current implementation is consistent.
        const r = view.getAll()[0];
        expect(r.n).toBeTruthy();
        const l = newListener(s);
        r.n.listen(l);
        r1.freq = 120e6;
        l.expectNotCalled(() => {
          expect(r.grouped).toContain(r1);
          done();
        });
      });
    });

    describe('Union', function () {
      it('should notify on member change', done => {
        const t = new Table('foo', true);
        const u = new Union();
        u.add(t);
        const l = newListener(s);
        u.n.listen(l);
        l.expectCalled(() => {
          t.add(dummyRecord);
        }, done);
      });
      // TODO test remove()
    });
  });
  
  return 'ok';
});
