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

define(['map/map-core'], (mapCore) => {
  'use strict';
  
  describe('map/map-core', function () {
    describe('StripeAllocator', function () {
      const StripeAllocator = mapCore._StripeAllocatorForTesting;

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

        expect(spy.callCount).toBe(0);
        a1.incRefCount();
        a1.incRefCount();
        a1.decRefCount();
        a1.decRefCount();
        expect(spy.callCount).toBe(0);
        a1.decRefCount();
        expect(spy.callCount).toBe(1);

        // was freed
        expect(allocator.allocate(1, 'shouldwork', ()=>{})).toBeTruthy();
      });
    });
  });
  
  return 'ok';
});