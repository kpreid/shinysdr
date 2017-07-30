// Copyright 2015, 2016 Kevin Reid <kpreid@switchb.org>
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

// Manages pop-up context menus

define(['./types', './values', './widget'], function (types, values, widget) {
  'use strict';

  var anyT = types.anyT;
  var ConstantCell = values.ConstantCell;
  var createWidgetExt = widget.createWidgetExt;

  var exports = {};
  
  var menuDialog = new WeakMap();
  var menuInner = new WeakMap();
  function Menu(widgetContext, widgetCtor, target) {
    var dialog = document.createElement('dialog');
    var innerElement = document.createElement('div');
    dialog.appendChild(innerElement);
    dialog.classList.add('menu-dialog');
    
    menuDialog.set(this, dialog);
    menuInner.set(this, innerElement);
    
    var menuContext = widgetContext.forMenu(function closeCallback() {
      dialog.close();
    });
    
    var widgetHandle = createWidgetExt(menuContext, widgetCtor, innerElement, new ConstantCell(target, anyT));
    
    dialog.addEventListener('mouseup', function (event) {
      if (event.target === dialog) {  // therefore not on content
        dialog.close();
      }
      event.stopPropagation();
    }, true);
    dialog.addEventListener('close', function (event) {
      if (dialog.parentNode) {
        dialog.parentNode.removeChild(dialog);
      }
      widgetHandle.destroy();  // TODO prevent reuse at this point
    }, true);
    
    Object.freeze(this);
  }
  exports.Menu = Menu;
  Menu.prototype.openAt = function(targetElOrEvent) {
    var dialog = menuDialog.get(this);
    dialog.ownerDocument.body.appendChild(dialog);
    // TODO: Per spec, aligning the dialog should be automatic if we pass the target to showModal, but it isn't in Chrome 47. Enable once it works properly (and rework the kludge for map features to be compatible).
    dialog.showModal(/* targetElOrEvent */);
    if (targetElOrEvent && targetElOrEvent.nodeType) {
      var dialogCR = dialog.getBoundingClientRect();
      var targetCR = targetElOrEvent.getBoundingClientRect();
      dialog.style.left = (
        Math.max(0, Math.min(document.body.clientWidth - dialogCR.width,
          targetCR.left + targetCR.width / 2 - dialogCR.width / 2))
      ) + 'px';
      dialog.style.top = (
        Math.max(0, Math.min(document.body.clientHeight - dialogCR.height,
          targetCR.bottom))
      ) + 'px';
    }
    //lifecycleInit(menuInner.get(this));  // TODO make this possible or make it unavoidable (widget does this implicitly in 0ms but menu can be delayed between create and open)
  };
  Menu.prototype.close = function() {
    menuDialog.get(this).close();
  };
  
  return Object.freeze(exports);
});
