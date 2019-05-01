// Copyright 2013, 2014, 2015, 2016, 2017, 2018 Kevin Reid and the ShinySDR contributors
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

define([], () => {
  const exports = {};
  
  // webkitAudioContext required for Safari as of version 10.1
  const AudioContext = (window.AudioContext || window.webkitAudioContext);
  exports.AudioContext = AudioContext;
  
  // Given a maximum acceptable delay, calculate the largest power-of-two buffer size which does not result in more than that delay.
  function delayToBufferSize(sampleRate, maxDelayInSeconds) {
    var maxBufferSize = sampleRate * maxDelayInSeconds;
    var powerOfTwoBufferSize = 1 << Math.floor(Math.log(maxBufferSize) / Math.LN2);
    // Size limits defined by the Web Audio API specification.
    powerOfTwoBufferSize = Math.max(256, Math.min(16384, powerOfTwoBufferSize));
    return powerOfTwoBufferSize;
  }
  exports.delayToBufferSize = delayToBufferSize;
  
  function showPlayPrompt() {
    const dialog = document.createElement('dialog');
    dialog.classList.add('unspecific-modal-dialog');
    // TODO class for styling
    
    dialog.textContent = 'This page provides a visualization of audio from your microphone, other available audio input device, or a file. It does not play any sound and does not record or transmit the audio or any derived information. (Or so this text claims.)';
    
    const ackButton = dialog.appendChild(document.createElement('p'))
        .appendChild(document.createElement('button'));
    ackButton.textContent = 'Continue';
  
    return new Promise((resolve, reject) => {
      ackButton.addEventListener('click', event => {
        dialog.close();
        resolve();
      }, true);
      dialog.addEventListener('close', event => {
        if (dialog.parentNode) {
          dialog.parentNode.removeChild(dialog);
        }
        reject(new Error('User canceled'));
      }, true);
      
      document.body.appendChild(dialog);
      requestAnimationFrame(() => {
        // Do this async so that if the browser doesn't support <dialog> features, they will still get a functional OK button.
        dialog.showModal();
      });
    });
  }
  
  // Cooperate with the Chrome autoplay policy, which says that audio contexts cannot be in 'running' state until a user interaction with the page (or prior interaction with the site).
  // https://developers.google.com/web/updates/2017/09/autoplay-policy-changes
  // The default UI prompt is intended for the standalone "audio toolbox" pages.
  function audioContextAutoplayHelper(audioContext, showUI=showPlayPrompt) {
    if (audioContext.state === 'suspended') {
      console.log('audioContextAutoplayHelper: prompting');
      return showUI().then(() => {
        console.log('audioContextAutoplayHelper: resuming after prompt');
        return audioContext.resume().then(() => {
          console.log('audioContextAutoplayHelper: successfully resumed');
        });
      });
    } else {
      console.log('audioContextAutoplayHelper: state is OK:', audioContext.state);
      return Promise.resolve();
    }
  }
  exports.audioContextAutoplayHelper = audioContextAutoplayHelper;
  
  return Object.freeze(exports);
});
