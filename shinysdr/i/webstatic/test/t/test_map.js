// Copyright 2016 Kevin Reid <kpreid@switchb.org>
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
  'map/map-core',
  'types',
  'values',
], (
  import_jasmine,
  import_testutil,
  import_map_core,
  import_types,
  import_values
) => {
  const {ji: {
    describe,
    expect,
    it,
    jasmine
  }} = import_jasmine;
  const {
    WidgetTester,
  } = import_testutil;
  const {
    _StripeAllocatorForTesting: StripeAllocator,
    GeoMap,
  } = import_map_core;
  const {
    anyT,
  } = import_types;
  const {
    ConstantCell,
    makeBlock
  } = import_values;
  
  describe('map/map-core', function () {
    describe('StripeAllocator', function () {
      const height = 13;  // arbitrary choice
    
      it('handles simple allocation up to full size', function () {
        const allocator = new StripeAllocator(10, Math.ceil(2.5 * height), height);
        
        const a1 = allocator.allocate(5, 'a1', ()=>{});
        expect([a1.y, a1.x]).toEqual([height * 0, 0]);
        const a2 = allocator.allocate(7, 'a2', ()=>{});
        expect([a2.y, a2.x]).toEqual([height * 1, 0]);
        const a3 = allocator.allocate(5, 'a3', ()=>{});
        expect([a3.y, a3.x]).toEqual([height * 0, 5]);
        const a4 = allocator.allocate(3, 'a4', ()=>{});
        expect([a4.y, a4.x]).toEqual([height * 1, 7]);
        expect(allocator.allocate(1, 'a5', ()=>{})).toBe(null);
      });

      it('will allocate over-width items', function () {
        const allocator = new StripeAllocator(10, height * 2, height);
        
        const a1 = allocator.allocate(20, 'a1', ()=>{});
        expect([a1.y, a1.x]).toEqual([height * 0, 0]);
        const a2 = allocator.allocate(7, 'a2', ()=>{});
        expect([a2.y, a2.x]).toEqual([height * 1, 0]);
        expect(allocator.allocate(7, 'a2', ()=>{})).toBe(null);
      });

      it('frees properly per refcount', function () {
        const allocator = new StripeAllocator(1, height, height);
        const spy = jasmine.createSpy();
        const a1 = allocator.allocate(1, 'a1', spy);
        
        // confirm cannot allocate more
        expect(allocator.allocate(1, 'nope', ()=>{})).toBe(null);

        expect(spy.calls.count()).toBe(0);
        a1.incRefCount();
        a1.incRefCount();
        a1.decRefCount();
        a1.decRefCount();
        expect(spy.calls.count()).toBe(0);
        a1.decRefCount();
        expect(spy.calls.count()).toBe(1);

        // was freed
        expect(allocator.allocate(1, 'shouldwork', ()=>{})).toBeTruthy();
      });
      
      it('coalesces spans of free space', function () {
        const allocator = new StripeAllocator(10, height, height);
        
        // allocate space in small chunks
        const a1 = allocator.allocate(3, 'a1', ()=>{});
        const a2 = allocator.allocate(3, 'a2', ()=>{});
        const a3 = allocator.allocate(3, 'a3', ()=>{});
        a1.decRefCount();
        a3.decRefCount();
        a2.decRefCount();
        
        // allocate a bigger thing
        expect(allocator.allocate(9, 'a4', ()=>{})).toBeTruthy();
      });
    });
    
    describe('GeoMap widget', function () {
      function makeStubTarget() {
        // TODO stop needing this boilerplate, somehow.
        return new ConstantCell(makeBlock({
          source: new ConstantCell(makeBlock({
            freq: new ConstantCell(0),
            rx_driver: new ConstantCell(makeBlock({
              output_type: new ConstantCell({sample_rate: 1}, anyT)
            })),
            components: new ConstantCell(makeBlock({}))
          })),
          receivers: new ConstantCell(makeBlock({
          }))
        }));
      }
    
      it('exists', function () {
        expect(typeof GeoMap).toBe('function');
      });
    
      it('should be successfully created', function () {
        const cell = makeStubTarget();
        const wt = new WidgetTester(GeoMap, cell);
        expect(wt.config.storage.getItem('viewCenterLat')).toBe('0');  // TODO: test against public interface -- of some sort -- rather than storage
        expect(wt.config.storage.getItem('viewCenterLon')).toBe('0');
        expect(wt.config.storage.getItem('viewZoom')).toBe('1');
      });
    
      // TODO Check reading initial position from PositionedDevice
    });
  });
  
  return 'ok';
});