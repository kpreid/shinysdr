// Copyright 2016, 2017, 2018 Kevin Reid <kpreid@switchb.org>
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
  'audio/analyser',
  'audio/bufferer',
  'audio/client-source',
  'audio/util',
  'audio/ws-stream',
  'events'
], (
  import_jasmine,
  import_audio_analyser,
  import_audio_bufferer,
  import_audio_client_source,
  import_audio_util,
  import_audio_ws_stream,
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
    AudioScopeAdapter,
  } = import_audio_analyser;
  const {
    AudioBuffererImpl: AudioBuffererImpl,
  } = import_audio_bufferer;
  const {
    handleUserMediaError_ForTesting: handleUserMediaError,
    AudioSourceSelector,
  } = import_audio_client_source;
  const {
    AudioContext,
  } = import_audio_util;
  const {
    minimizeSampleRate_ForTesting: minimizeSampleRate,
  } = import_audio_ws_stream;
  const {
    Scheduler,
  } = import_events;
  

  function waitForOnePostMessage() {
    return new Promise(resolve => {
      const {port1, port2} = new MessageChannel();
      port2.onmessage = event => { resolve(); };
      port1.postMessage('dummy');
    });
  }
  
  describe('audio', () => {
    // TODO: test connectAudio (requires server side websocket stub)

    // Only a limited number of AudioContexts can be created, and we can't stub them, so all tests share one. This doesn't do too much harm since there isn't any global state that we need to worry about in them.
    const audioContext = new AudioContext();

    let scheduler;
    beforeEach(() => {
      scheduler = new Scheduler();
    });
    
    describe('AudioBuffererImpl', () => {
      it('should copy samples', done => {
        const channel = new MessageChannel();
        const post = channel.port1.postMessage.bind(channel.port1);
        const b = new AudioBuffererImpl(10000, channel.port2);
        post(['setFormat', 2, 10000]);
        
        function read(n) {
          const l = new Float32Array(n);
          const r = new Float32Array(n);
          b.produceSamples(l, r);
          return [Array.prototype.slice.call(l), Array.prototype.slice.call(r)];
        }
        
        const samples = new Float32Array([1, 2, 3, 4, 5, 6, 7, 8, 9, 10]);
        post(['acceptSamples', samples]);
        
        // We need to wait for the messages to be delivered. There is nothing in the interface to allow us to wait directly for it.
        waitForOnePostMessage().then(() => {
          expect(read(4)).toEqual([[1, 3, 5, 7], [2, 4, 6, 8]]);
          expect(read(4)).toEqual([[9, 9, 9, 9], [10, 10, 10, 10]]);
          done();
        });
      });
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
        expect(message).toMatch(/^Failed to testing1 \(could not open device\)\. blah(\nPlease try reloading or reopening the tab.)?$/);
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
  
    describe('AudioSourceSelector', () => {
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
        new AudioSourceSelector(scheduler, audioContext, stubMediaDevices, sessionStorage);
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