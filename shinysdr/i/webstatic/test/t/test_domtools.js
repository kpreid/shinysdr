// Copyright 2017 Kevin Reid <kpreid@switchb.org>
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
  'domtools',
], (
  import_jasmine,
  import_domtools
) => {
  const {ji: {
    afterEach,
    beforeEach,
    describe,
    expect,
    it,
    jasmine,
  }} = import_jasmine;
  const {
    isVisibleInLayout,
    lifecycleDestroy,
    lifecycleInit,
    reveal,
  } = import_domtools;
  
  let container;
  beforeEach(() => {
    container = document.body.appendChild(document.createElement('div'));
  });
  afterEach(() => {
    if (container && container.parentNode) {
      container.parentNode.removeChild(container);
    }
  });
  
  describe('domtools', () => {
    describe('lifecycle', () => {
      // TODO: test lifecycle functions more
      
      // TODO this tests more than that in a big lump
      it('should destroy non-immediate descendants', () => {
        const a = document.createElement('div');
        const b = a.appendChild(document.createElement('div'));
        const c = b.appendChild(document.createElement('div'));
        
        let state = [0, 0, 0, 0];
        a.addEventListener('shinysdr:lifecycleinit', event => {
          state[0]++;
        });
        a.addEventListener('shinysdr:lifecycledestroy', event => {
          state[1]++;
        });
        c.addEventListener('shinysdr:lifecycleinit', event => {
          state[2]++;
        });
        c.addEventListener('shinysdr:lifecycledestroy', event => {
          state[3]++;
        });
        
        // no effect if not in dom
        lifecycleInit(a);
        expect(state).toEqual([0, 0, 0, 0]);
        
        // init is not recursive
        container.appendChild(a);
        lifecycleInit(a);
        expect(state).toEqual([1, 0, 0, 0]);
        
        // just preparation for destroy
        lifecycleInit(c);
        expect(state).toEqual([1, 0, 1, 0]);
        
        // destroy does both
        lifecycleDestroy(a);
        expect(state).toEqual([1, 1, 1, 1]);
        
        // destroy is idempotent
        lifecycleDestroy(a);
        expect(state).toEqual([1, 1, 1, 1]);
      });
    });
    
    describe('isVisibleInLayout', () => {
      // TODO: More tests
      it('should exclude a detached element', () => {
        const el = document.createElement('button');
        expect(isVisibleInLayout(el)).toBeFalsy();
        container.appendChild(el);
        expect(isVisibleInLayout(el)).toBeTruthy();
      });
      
      it('should exclude an element in a hidden container', () => {
        const outer = container.appendChild(document.createElement('div'));
        const el = outer.appendChild(document.createElement('button'));
        expect(isVisibleInLayout(el)).toBeTruthy();
        outer.style.display = 'none';
        expect(isVisibleInLayout(el)).toBeFalsy();
      });
    });
    
    describe('reveal', () => {
      it('should succeed trivially', () => {
        expect(reveal(container)).toBe(true);
      });

      it('should open a <details> parent', () => {
        const d = container.appendChild(document.createElement('details'));
        const target = d.appendChild(document.createElement('input'));
        expect(isVisibleInLayout(target)).toBeFalsy();
        expect(d.open).toBe(false);

        expect(reveal(target)).toBe(true);

        expect(isVisibleInLayout(target)).toBeTruthy();
        expect(d.open).toBe(true);
      });
      
      it('should fire a bubbling event', () => {
        const node1 = container.appendChild(document.createElement('div'));
        const node2 = node1.appendChild(document.createElement('div'));
        const node3 = node2.appendChild(document.createElement('input'));

        const listener1 = jasmine.createSpy('listener1');
        node1.addEventListener('shinysdr:reveal', listener1, false);
        const listener2 = jasmine.createSpy('listener2');
        node2.addEventListener('shinysdr:reveal', listener2, false);

        expect(reveal(node3)).toBe(true);

        expect(listener1).toHaveBeenCalledTimes(1);
        expect(listener2).toHaveBeenCalledTimes(1);
        // is the same event in both cases
        expect(listener2).toHaveBeenCalledWith(...listener1.calls.argsFor(0));
      });
      
      it('should report failure on an orphaned node', () => {
        const d = document.createElement('details');
        const target = d.appendChild(document.createElement('input'));
        expect(reveal(target)).toBe(false);
      });
    });
  });
  
  return 'ok';
});