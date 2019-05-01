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

define([
  '../types',
  '../values',
  '../widgets',
  '../widgets/basic',
], (
  import_types,
  import_values,
  widgets,
  import_widgets_basic
) => {
  const {
    anyT,
    blockT,
    booleanT,
    stringT,
  } = import_types;
  const {
    ConstantCell,
    LocalCell,
    LocalReadCell,
    StorageCell,
    makeBlock,
  } = import_values;
  const {
    Banner,
    Block,
  } = import_widgets_basic;

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
      showMessage('Failed to ' + whatWeWereDoing + ' (unexpected error). ' + e.name + ': ' + e.message);
    } else if (e) {
      showMessage('Failed to ' + whatWeWereDoing + ' (unexpected error). ' + String(e));
      throw e;
    } else {
      throw e;
    }
  }
  exports.handleUserMediaError_ForTesting = handleUserMediaError;
  
  const SOURCE_TYPE_PREFIX_USER_MEDIA = 'UserMedia.';
  const SOURCE_TYPE_PREFIX_URL = 'URL.';
  
  function UserMediaDeviceListCell(mediaDevices) {
    const cell = new LocalReadCell(anyT, [{
      sourceSpec: SOURCE_TYPE_PREFIX_USER_MEDIA,
      label: 'Input: Default',
    }]);
    
    let updateList = () => {
      mediaDevices.enumerateDevices().then(mediaDeviceInfos => {
        const resultList = [];
        Array.from(mediaDeviceInfos).forEach(mediaDeviceInfo => {
          if (mediaDeviceInfo.kind !== 'audioinput') return;
          // TODO use mediaDeviceInfo.groupId for sorting
          resultList.push({
            sourceSpec: SOURCE_TYPE_PREFIX_USER_MEDIA + mediaDeviceInfo.deviceId,
            label: 'Input: ' + String(mediaDeviceInfo.label || mediaDeviceInfo.deviceId),
          });
        });
        
        Object.freeze(resultList);
        cell._update(resultList);
      }, e => {
        // TODO better reporting
        handleUserMediaError(e, console.error.bind(console), 'list audio devices');
        cell._update(Object.freeze([]));
      });
    };
    
    // Note: Have not managed to see this event fired in practice (Chrome and Firefox on Mac) so the consequences are not tested.
    mediaDevices.addEventListener('devicechange', event => updateList(), false);
    updateList();
    
    return cell;
  }
  
  function SwitchableAudioNode(audioContext) {
    const node = audioContext.createGain();  // dummy node
    let currentSource = null;
    function setSource(newSource) {
      if (newSource !== null) {
        // Doing this first acts as parameter validation before we accept newSource as the value of currentSource.
        newSource.connect(node);
      }
      if (newSource !== currentSource && currentSource !== null) {
        currentSource.disconnect(node);
      }
      currentSource = newSource;
    }
    // TODO: Wrap node to look like a more generic node.
    return [setSource, node];
  }
  
  const nullAudioSourceBlock = Object.freeze(makeBlock({
    ready: new ConstantCell(false),
    node: new ConstantCell(null, anyT),
  }));

  function makeSourceBlock(audioContext, sourceSpec) {
    const match = /^(\w+\.)(.*$)/.exec(sourceSpec);
    // console.log('parsing', sourceSpec, match && match[1], match && match[2]);
    switch (match ? match[1] : '') {
      default:
        if (sourceSpec !== undefined) {
          console.error('AudioSourceOpener: bad source spec ' + JSON.stringify(sourceSpec));
        }
        return nullAudioSourceBlock;
      case SOURCE_TYPE_PREFIX_USER_MEDIA: {
        const deviceId = match[2];
        const deviceIdConstraint = deviceId ? { exact: deviceId } : null;

        const readyCell = new LocalReadCell(booleanT, false);
        const nodeCell = new LocalReadCell(anyT, null);
        const errorCell = new LocalReadCell(stringT, '');
        
        navigator.mediaDevices.getUserMedia({
          audio: {
            deviceId: deviceIdConstraint,
            // If we do not disable default-enabled echoCancellation then we get mono
            // audio on Chrome. See:
            //    https://bugs.chromium.org/p/chromium/issues/detail?id=387737
            echoCancellation: { exact: false }  // using 'ideal:' doesn't help.
          }
        }).then((stream) => {
          // TODO: There is supposedly a better version of this in the future (MediaStreamTrackSource)
          // TODO: In case selector gets changed multiple times, have a token to cancel earlier requests
          nodeCell._update(audioContext.createMediaStreamSource(stream));
          readyCell._update(true);
        }, (e) => {
          handleUserMediaError(e, errorCell._update.bind(errorCell),
              'open audio device ' + JSON.stringify(deviceId));
        });
        return makeBlock({
          ready: readyCell,
          error: errorCell,
          node: nodeCell,
        });
      }
      case SOURCE_TYPE_PREFIX_URL: {
        const url = match[2];
        if (url === '') {
          // "not yet selected" non-error case
          return nullAudioSourceBlock;
        }
        
        const readyCell = new LocalReadCell(booleanT, false);
        const errorCell = new LocalReadCell(stringT, '');
        const el = document.createElement('audio');
        el.src = url;
        el.addEventListener('error', event => {
          errorCell._update(el.error.message);
        });
        el.addEventListener('canplay', event => {
          readyCell._update(true);
        });
        el.load();
        
        return makeBlock({
          ready: readyCell,
          error: errorCell,
          element: new ConstantCell(el, anyT),  // TODO grab this for a widget
          node: new ConstantCell(audioContext.createMediaElementSource(el), anyT),
        });
      }
    }
  }

  function AudioSourceSelector(scheduler, audioContext, mediaDevices, storage) {
    const [setSource, outputNode] = new SwitchableAudioNode(audioContext);
    const userMediaDeviceListCell = new UserMediaDeviceListCell(mediaDevices);
    
    const sourceSpecCell = new StorageCell(storage, stringT, SOURCE_TYPE_PREFIX_USER_MEDIA, 'device');
    if (sourceSpecCell.get().startsWith(SOURCE_TYPE_PREFIX_URL + 'blob:')) {
      // Blobs are ephemeral, do not use them
      sourceSpecCell.set(SOURCE_TYPE_PREFIX_USER_MEDIA);
    }
    scheduler.startNow(function updateToEnumeratedDefaultDevice() {
      if (sourceSpecCell.get() !== SOURCE_TYPE_PREFIX_USER_MEDIA) {
        // This is only done once on startup
        return;
      }
      const firstListedDevice = userMediaDeviceListCell.get()[0];
      if (firstListedDevice.sourceSpec === SOURCE_TYPE_PREFIX_USER_MEDIA) {
        // Not ready yet
        userMediaDeviceListCell.n.listen(updateToEnumeratedDefaultDevice);
        return;
      }
      sourceSpecCell.set(firstListedDevice.sourceSpec);
    });
    
    const currentSourceCell = new LocalCell(blockT, nullAudioSourceBlock);
    const nextSourceCell = new LocalCell(blockT, nullAudioSourceBlock);
    const playthroughCell = new StorageCell(storage, booleanT, false, 'playthrough');
    let playthroughConnected = false;
    
    scheduler.startNow(function checkSourceSpec() {
      const sourceBlock = makeSourceBlock(audioContext, sourceSpecCell.depend(checkSourceSpec));
      nextSourceCell.set(sourceBlock);
    });
    scheduler.startNow(function switchSource() {
      const nextSource = nextSourceCell.depend(switchSource);
      if (nextSource.ready.depend(switchSource)) {
        currentSourceCell.set(nextSource);
        nextSourceCell.set(nullAudioSourceBlock);
      }
    });
    scheduler.startNow(function connectSourceNode() {
      setSource(currentSourceCell.depend(connectSourceNode).node.depend(connectSourceNode));
    });
    scheduler.startNow(function updatePlaythrough() {
      const value = playthroughCell.depend(updatePlaythrough);
      if (playthroughConnected !== value) {
        playthroughConnected = value;
        if (value) {
          outputNode.connect(audioContext.destination);
        } else {
          outputNode.disconnect(audioContext.destination);
        }
      }
    });

    makeBlock(this);
    this.source_spec = sourceSpecCell;
    this.current_source = currentSourceCell;
    this.next_source = nextSourceCell;
    this.device_list = userMediaDeviceListCell;
    this.playthrough = playthroughCell;
    Object.defineProperty(this, '_implements_shinysdr.client.audio.AudioSourceSelector', {});
    Object.defineProperty(this, 'source', {value: outputNode});
  }
  exports.AudioSourceSelector = AudioSourceSelector;
  
  function AudioSourceSelectorWidget(config) {
    Block.call(this, config, function (block, addWidget, ignore, setInsertion, setToDetails, getAppend) {
      const scheduler = config.scheduler;
      const userMediaDeviceListCell = block.device_list;
      ignore('device_list');
      
      this.element.classList.remove('frame');  // kludge
      
      // This is not a standard select widget because the menu content changes
      const sourcePickerMenu = getAppend().appendChild(document.createElement('select'));
      let oldSourceSpec = null;
      scheduler.startNow(function updateSourceMenu() {
        const currentSourceSpec = block.source_spec.depend(updateSourceMenu);

        sourcePickerMenu.textContent = '';
        function addOption(item) {
          const option = sourcePickerMenu.appendChild(document.createElement('option'));
          option.value = item.sourceSpec;
          option.textContent = item.label;
        }
        function addSpec(sourceSpec) {
          // non-URLs are non-arbitrary
          if (sourceSpec.startsWith(SOURCE_TYPE_PREFIX_URL) && sourceSpec !== SOURCE_TYPE_PREFIX_URL) {
            addOption({
              sourceSpec: sourceSpec,
              label: 'URL: ' + sourceSpec.substring(SOURCE_TYPE_PREFIX_URL.length),
            });
          }
        }
        userMediaDeviceListCell.depend(updateSourceMenu).forEach(addOption);
        addSpec(currentSourceSpec);
        if (oldSourceSpec && oldSourceSpec !== currentSourceSpec) addSpec(oldSourceSpec);
        addOption({
          sourceSpec: 'URL.',
          label: 'File or URL…',
        });
        sourcePickerMenu.value = currentSourceSpec;
      });
      sourcePickerMenu.addEventListener('change', event => {
        const newSourceSpec = sourcePickerMenu.value;
        const replacing = block.source_spec.get();
        if (/\../.test(replacing)) {
          oldSourceSpec = replacing;
        }
        oldSourceSpec = block.source_spec.get();
        block.source_spec.set(newSourceSpec);
      });
      
      // External input fields
      const urlPanel = getAppend().appendChild(document.createElement('div'));
      urlPanel.classList.add('widget-AudioSourceSelectorWidget-subpanel');
      const urlField = urlPanel.appendChild(document.createElement('input'));
      const urlEnterButton = urlPanel.appendChild(document.createElement('button'));
      urlEnterButton.textContent = 'Load URL';
      const filePanel = getAppend().appendChild(document.createElement('div'));
      filePanel.appendChild(document.createTextNode('or '));
      filePanel.classList.add('widget-AudioSourceSelectorWidget-subpanel');
      const fileField = filePanel.appendChild(document.createElement('input'));
      fileField.type = 'file';
      scheduler.startNow(function updateUrlPanel() {
        const sourceSpec = block.source_spec.depend(updateUrlPanel);
        urlPanel.style.display = sourceSpec === SOURCE_TYPE_PREFIX_URL ? '' : 'none';
        filePanel.style.display = sourceSpec === SOURCE_TYPE_PREFIX_URL ? '' : 'none';
        urlField.value = oldSourceSpec && oldSourceSpec.startsWith(SOURCE_TYPE_PREFIX_URL) ? oldSourceSpec.substring(SOURCE_TYPE_PREFIX_URL.length) : '';
      });
      urlEnterButton.addEventListener('click', event => {
        block.source_spec.set(SOURCE_TYPE_PREFIX_URL + urlField.value);
      });
      fileField.addEventListener('change', event => {
        const files = fileField.files;
        if (files.length) {
          block.source_spec.set(SOURCE_TYPE_PREFIX_URL + URL.createObjectURL(files[0]));
          // TODO: Also do a revokeObjectURL
        }
      });
      
      ignore('source_spec');
      addWidget('current_source', AudioSourceBlockWidget);
      addWidget('next_source', AudioSourceBlockWidget);
    }, false);
  }
  // TODO: get right of mutable widget table kludge
  widgets['interface:shinysdr.client.audio.AudioSourceSelector'] = AudioSourceSelectorWidget;
  function AudioSourceBlockWidget(config) {
    Block.call(this, config, function (block, addWidget, ignore, setInsertion, setToDetails, getAppend) {
      ignore('ready');
      ignore('node');
      if ('element' in block) {
        ignore('element');
        const audioElement = block.element.depend(config.rebuildMe);
        getAppend().appendChild(audioElement);
        // audioElement.style.width = '100%';
        audioElement.controls = true;
      }
      addWidget('error', Banner);
    }, true);
  }
  
  return Object.freeze(exports);
});
