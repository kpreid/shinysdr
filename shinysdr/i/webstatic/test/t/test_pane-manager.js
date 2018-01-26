// Copyright 2017, 2018 Kevin Reid <kpreid@switchb.org>
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
  'events',
  'pane-manager',
  'types',
  'values',
  'widget',
], (
  import_jasmine,
  import_domtools,
  import_events,
  import_pane_manager,
  import_types,
  import_values,
  import_widget
) => {
  const {ji: {
    afterEach,
    beforeEach,
    describe,
    expect,
    it,
    xit
  }} = import_jasmine;
  const {
    isVisibleInLayout,
    lifecycleInit,
    reveal,
  } = import_domtools;
  const {
    Scheduler,
  } = import_events;
  const {
    PaneListWidget,
    PaneManager,
  } = import_pane_manager;
  const {
    stringT,
  } = import_types;
  const {
    ConstantCell,
    LocalCell,
    makeBlock,
  } = import_values;
  const {
    Context,
    createWidgetExt,
  } = import_widget;
  
  describe('pane-manager', () => {
    let container, context, paneListElement;
    beforeEach(() => {
      container = document.body.appendChild(document.createElement('div'));
      paneListElement = container.appendChild(document.createElement('div'));
      context = new Context({
        scheduler: new Scheduler(window),
      });
    });
    afterEach(() => {
      if (container && container.parentNode) {
        container.parentNode.removeChild(container);
      }
      // TODO: kill scheduler?
    });
  
    function newPM() {
      const pm = new PaneManager(
        context,
        container,
        new ConstantCell(makeBlock({})));
      createWidgetExt(
        context,
        PaneListWidget,
        paneListElement.appendChild(document.createElement('div')),
        new ConstantCell(pm));
      return pm;
    }
    function getFrameEl(pane) {
      // Kludge for testing since frame isn't exposed right now.
      expect(pane.contentElement).toBeTruthy();
      const frameElement = pane.contentElement.parentNode;
      expect(frameElement).toBeTruthy();
      return frameElement;
    }
    
    describe('PaneManager', () => {
      it('should create structure for a new pane', () => {
        const pm = newPM();
        const pane = pm.newPane();

        const frameElement = getFrameEl(pane);  // also checks contentElement
        expect(frameElement.classList.contains('pane-frame')).toBeTruthy();

        // TODO: Feature temporarily disabled.
        // const hideButton = frameElement.querySelector('.pane-hide-button');
        // expect(hideButton).toBeTruthy();
      });
      
      // TODO: Feature temporarily disabled.
      xit('should hide a pane from the UI', () => {
        const pm = newPM();
        const pane = pm.newPane();
        const el = getFrameEl(pane);
        expect(isVisibleInLayout(el)).toBeTruthy();  // check assumption

        const hideButton = container.querySelector('.pane-hide-button');
        expect(isVisibleInLayout(el)).toBeTruthy();
        hideButton.click();
        expect(isVisibleInLayout(el)).toBeFalsy();
        
        // TODO: also need showing panes from the UI, of course
      });
      
      it('should hide and show panes programmatically', () => {
        const pm = newPM();
        const pane = pm.newPane();
        const el = getFrameEl(pane);
        
        expect(isVisibleInLayout(el)).toBeTruthy();  // check assumption
        pane.hide();
        expect(isVisibleInLayout(el)).toBeFalsy();
        pane.show();
        expect(isVisibleInLayout(el)).toBeTruthy();
      });
      
      it('should fire resize events', done => {
        // TODO: Consider building a custom non-global resize notifiation for everyone to use.
        
        // Resize events are global. First, let any already-queued ones from other tests fire.
        requestAnimationFrame(() => {
          
          let resized = 0;
          window.addEventListener('resize', () => { resized++; }, false);
          expect(resized).toBe(0);  // sanity check
          const pane = newPM().newPane();
          expect(resized).toBe(1);  // new visible panes counts as resize
          pane.hide();
          requestAnimationFrame(() => {  // wait for async
            expect(resized).toBe(2);
            done();
          });
        });
      });
      
      it('should allow removing panes and fire lifecycle events', () => {
        const pm = newPM();
        const pane = pm.newPane();
        
        // No init event because panes start empty at the moment.
        
        let seen = 0;
        const testElement = pane.contentElement.appendChild(document.createElement('div'));
        testElement.addEventListener('shinysdr:lifecycledestroy', event => {
          seen++;
        }, false);
        expect(isVisibleInLayout(testElement)).toBeTruthy();
        lifecycleInit(testElement);
        
        pane.delete();
        expect(isVisibleInLayout(testElement)).toBeFalsy();
        expect(seen).toBe(1);
      });
      
      it('should support reveal()', () => {
        const pm = newPM();
        const pane = pm.newPane();
        const el = getFrameEl(pane);
        
        expect(isVisibleInLayout(el)).toBeTruthy();  // check assumption
        pane.hide();
        expect(isVisibleInLayout(el)).toBeFalsy();
        reveal(pane.contentElement);
        expect(isVisibleInLayout(el)).toBeTruthy();
      });
      
      it('should display a title for a pane', done => {
        const titleCell = new LocalCell(stringT, 'testTitle');
        const pm = newPM();
        const pane = pm.newPane({titleCell: titleCell});
        expect(getFrameEl(pane).querySelector('h2').textContent).toBe('testTitle');
        titleCell.set('title2');
        // TODO: Wait for a notification cycle and THEN delay
        requestAnimationFrame(() => {
          expect(getFrameEl(pane).querySelector('h2').textContent).toBe('title2');
          done();
        });
      });
      
      it('should maintain a list of panes', done => {
        const pm = newPM();
        pm.newPane({titleCell: new ConstantCell('foo')});
        
        requestAnimationFrame(() => {
          expect(paneListElement.textContent).toContain('foo');
          done();
        });
      });
      
      it('should create panes with widgets from existing HTML', () => {
        // TODO: this element name (using an element name at all) is legacy
        const templateFrameEl = container.appendChild(document.createElement('shinysdr-pane'));
        templateFrameEl.appendChild(document.createElement('h2'))
            .appendChild(document.createTextNode('existing title'));
        
        newPM();
        
        // TODO: check widget nature of new pane
        expect(paneListElement.textContent).toContain('existing title');
      });
    });
  });
  
  return 'ok';
});
