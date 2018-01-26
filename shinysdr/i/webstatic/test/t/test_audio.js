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
  'audio',
  'events'
], (
  import_jasmine,
  import_audio,
  import_events
) => {
  const {ji: {
    beforeEach,
    describe,
    expect,
    it,
  }} = import_jasmine;
  const {
    AudioAnalyserAdapter,
    AudioContext,
    AudioScopeAdapter, 
    UserMediaSelector,
    handleUserMediaError_ForTesting: handleUserMediaError,
    minimizeSampleRate_ForTesting: minimizeSampleRate,
  } = import_audio;
  const {
    Scheduler,
  } = import_events;
  
  describe('audio', () => {
    // TODO: test connectAudio (requires server side websocket stub)

    // Only a limited number of AudioContexts can be created, and we can't stub them, so all tests share one. This doesn't do too much harm since there isn't any global state that we need to worry about in them.
    const audioContext = new AudioContext();

    let scheduler;
    beforeEach(() => {
      scheduler = new Scheduler();
    });

    describe('AudioAnalyserAdapter', () => {
      it('should be instantiable', () => {
        new AudioAnalyserAdapter(scheduler, audioContext);
        expect(1).toBe(1);  // dummy expect for "this does not throw" test
      });
      
      it('should connect and disconnect', () => {
        const source = audioContext.createOscillator();
        const adapter = new AudioAnalyserAdapter(scheduler, audioContext);
        adapter.connectFrom(source);
        adapter.disconnectFrom(source);
        expect(1).toBe(1);  // dummy expect for "this does not throw" test
      });

      it('should have a subscribable output cell', done => {
        const adapter = new AudioAnalyserAdapter(scheduler, audioContext);
        const cell = adapter.fft;
        let finished = false;
        
        /* const subscription = */ cell.subscribe(value => {
          if (finished) return;
          finished = true;
          expect(value.length).toEqual(2);
          expect(value[0]).toEqual({freq: 0, rate: audioContext.sampleRate});
          expect(value[1].constructor).toEqual(Float32Array);
          // subscription.unsubscribe();  // TODO implement unsubscription.
          adapter.paused.set(true);
          done();
        });
        adapter.paused.set(false);
      });
      
      // TODO: test gathering actual plausible data
    });

    describe('AudioScopeAdapter', () => {
      it('should be instantiable', () => {
        new AudioScopeAdapter(scheduler, audioContext);
        expect(1).toBe(1);  // dummy expect for "this does not throw" test
      });
      
      it('should connect and disconnect', () => {
        const source = audioContext.createOscillator();
        const adapter = new AudioScopeAdapter(scheduler, audioContext);
        adapter.connectFrom(source);
        adapter.disconnectFrom(source);
        expect(1).toBe(1);  // dummy expect for "this does not throw" test
      });

      // TODO: Implement unsubscription so that we can enable this test without burning CPU forever after.
      // it('should have a subscribable output cell', done => {
      //   const adapter = new AudioScopeAdapter(scheduler, audioContext);
      //   const cell = adapter.scope;
      //   let finished = false;
      //   
      //   const subscription = cell.subscribe(value => {
      //     if (finished) return;
      //     finished = true;
      //     expect(value.length).toEqual(2);
      //     expect(value[0]).toEqual({});
      //     expect(value[1].constructor).toEqual(Float32Array);
      //     // subscription.unsubscribe();  // TODO implement unsubscription.
      //     done();
      //   });
      // });
      
      // TODO: test gathering actual plausible data
    });

    describe('handleUserMediaError', () => {
      function stubMediaError(name) {
        // Chrome does not seem to expose the constructor of the real exception so this is the best we can do.
        const e = new Error('blah');
        e.name = name;
        return e;
      }
      
      it('should give a specific message on PermissionDeniedError', () => {
        let message;
        handleUserMediaError(
            stubMediaError('PermissionDeniedError'),
            m => { message = m; },
            'testing1');
        expect(message).toBe('Failed to testing1 (permission denied). blah');
      });
      it('should pass on a general message', () => {
        let message;
        handleUserMediaError(
            stubMediaError('NotReadableError'),  // an example we have seen from Firefox
            m => { message = m; },
            'testing1');
        expect(message).toBe('Failed to testing1 (could not open device). blah');
      });
      it('should resort to throwing on an arbitrary object', () => {
        let message;
        expect(() => {
          handleUserMediaError(
              9,
              m => { message = m; },
              'testing1');
        }).toThrow(9);
        expect(message).toBe('9');
      });
      it('should resort to throwing on undefined', () => {
        let message;
        expect(() => {
          handleUserMediaError(
              undefined,
              m => { message = m; },
              'testing1');
        }).toThrow(undefined);
      });
    });
  
    describe('UserMediaSelector', () => {
      const stubMediaDevices = Object.freeze({
        addEventListener(name, listener, useCapture) {},
        
        enumerateDevices() {
          return new Promise(resolve => resolve([]));
        }
      });
      
      beforeEach(() => {
        sessionStorage.clear();
      });
      
      it('should be instantiable', () => {
        new UserMediaSelector(scheduler, audioContext, stubMediaDevices, sessionStorage);
        expect(1).toBe(1);  // dummy expect for "this does not throw" test
      });
      
      // TODO: tests of functionality
    });
    
    describe('minimizeSampleRate', () => {
      it('should return a reduced rate when possible', () => {
        expect(minimizeSampleRate(192000, 40000)).toBe(48000);
      });
      it('should preserve an exact match', () => {
        expect(minimizeSampleRate(44100, 44100)).toBe(44100);
      });
      it('should return the input rate if it is smaller than the limit', () => {
        expect(minimizeSampleRate(22050, 40000)).toBe(22050);
      });
    });
  });
  
  return 'ok';
});