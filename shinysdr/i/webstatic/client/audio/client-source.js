// Copyright 2013, 2014, 2015, 2016, 2017, 2018 Kevin Reid <kpreid@switchb.org>
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
  '../events',
  '../types',
  '../values',
], (
  import_events,
  import_types,
  import_values
) => {
  const {
    Notifier,
  } = import_events;
  const {
    EnumT,
    NoticeT,
  } = import_types;
  const {
    ConstantCell,
    LocalReadCell,
    StorageCell,
    cellPropOfBlock,
    makeBlock,
  } = import_values;

  const exports = {};
  
  function handleUserMediaError(e, showMessage, whatWeWereDoing) {
    // Note: Empirically, e is a NavigatorUserMediaError but that ctor is not exposed so we can't say instanceof.
    if (e && e.name === 'PermissionDeniedError') {
      // Permission error.
      // Note: Empirically, e.message is empty on Chrome.
      showMessage('Failed to ' + whatWeWereDoing + ' (permission denied). ' + e.message);
    } else if (e && e.name === 'NotReadableError') {
      let message = 'Failed to ' + whatWeWereDoing + ' (could not open device). ' + e.message;
      if (navigator.userAgent.match('Firefox')) {
        // Known issue; give advice rather than just being broken.
        message += '\nPlease try reloading or reopening the tab.';
      }
      showMessage(message);
    } else if (e && e.name) {
      showMessage(e.name);
    } else if (e) {
      showMessage(String(e));
      throw e;
    } else {
      throw e;
    }
  }
  exports.handleUserMediaError_ForTesting = handleUserMediaError;
  
  function MediaDeviceSelector(mediaDevices, storage) {
    let shapeNotifier = new Notifier();
    let selectorCell = null;  // set by enumerate()
    let errorCell = this.error = new LocalReadCell(new NoticeT(false), '');
    
    Object.defineProperty(this, '_reshapeNotice', {value: shapeNotifier});
    
    let enumerate = () => {
      mediaDevices.enumerateDevices().then(deviceInfos => {
        const deviceEnumTable = {};
        let defaultDeviceId = 'default';
        Array.from(deviceInfos).forEach(deviceInfo => {
          if (deviceInfo.kind !== 'audioinput') return;
          if (!defaultDeviceId) {
            defaultDeviceId = deviceInfo.deviceId;
          }
          deviceEnumTable[deviceInfo.deviceId] = String(deviceInfo.label || deviceInfo.deviceId);
          // TODO use deviceInfo.groupId as part of enum sort key
        });
        // TODO: StorageCell isn't actually meant to be re-created in this fashion and will leak stuff. Fix StorageCell.
        this.device = selectorCell = new StorageCell(storage, new EnumT(deviceEnumTable), defaultDeviceId, 'device');
        shapeNotifier.notify();
        errorCell._update('');
      }, e => {
        handleUserMediaError(e, errorCell._update.bind(errorCell), 'list audio devices');
      });
    };
    // Note: Have not managed to see this event fired in practice (Chrome and Firefox on Mac).
    mediaDevices.addEventListener('devicechange', event => enumerate(), false);
    enumerate();
  }
  
  function UserMediaOpener(scheduler, audioContext, deviceIdCell) {
    // TODO: Does not need to be an unbreakable notify loop; have something which is a generalization of DerivedCell that handles async computations.
    const output = audioContext.createGain();  // dummy node to be switchable
    
    makeBlock(this);
    let errorCell = this.error = new LocalReadCell(new NoticeT(false), '');
    Object.defineProperty(this, 'source', {value: output});
    
    let previousSource = null;
    function setOutput(newSource) {
      if (newSource !== previousSource && previousSource !== null) {
        previousSource.disconnect(output);
      }
      if (newSource !== null) {
        newSource.connect(output);
      }
      previousSource = newSource;
    }
    
    scheduler.startNow(function update() {
      const deviceId = deviceIdCell.depend(update);
      if (typeof deviceId !== 'string') {
        setOutput(null);
      } else {
        navigator.mediaDevices.getUserMedia({
          audio: {
            deviceId: { exact: deviceId },
            // If we do not disable default-enabled echoCancellation then we get mono
            // audio on Chrome. See:
            //    https://bugs.chromium.org/p/chromium/issues/detail?id=387737
            echoCancellation: { exact: false }  // using 'ideal:' doesn't help.
          }
        }).then((stream) => {
          // TODO: There is supposedly a better version of this in the future (MediaStreamTrackSource)
          // TODO: In case selector gets changed multiple times, have a token to cancel earlier requests
          setOutput(audioContext.createMediaStreamSource(stream));
          errorCell._update('');
        }, (e) => {
          setOutput(null);
          // TODO: Get device's friendly name for error message
          handleUserMediaError(e, errorCell._update.bind(errorCell),
              'open audio device ' + JSON.stringify(deviceId));
        });
      }
    });
  }

  function UserMediaSelector(scheduler, audioContext, mediaDevices, storage) {
    const mediaDeviceSelector = new MediaDeviceSelector(mediaDevices, storage);
    const userMediaOpener = new UserMediaOpener(scheduler, audioContext,
        cellPropOfBlock(scheduler, mediaDeviceSelector, 'device', false));
    
    // TODO: this is not a good block/cell structure, we are exposing our implementation organization.
    makeBlock(this);
    this.selector = new ConstantCell(mediaDeviceSelector);
    this.opener = new ConstantCell(userMediaOpener);
    Object.defineProperty(this, 'source', {value: userMediaOpener.source});
  }
  exports.UserMediaSelector = UserMediaSelector;
  
  return Object.freeze(exports);
});
