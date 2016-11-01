// Copyright 2013, 2014, 2015, 2016 Kevin Reid <kpreid@switchb.org>
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

define(['./widgets/appui', './widgets/basic', './widgets/dbui', './widgets/spectrum'], function (widgets_appui, widgets_basic, widgets_dbui, widgets_spectrum) {
  'use strict';

  // TODO: This module is leftover from refactoring and only makes the namespace used for looking up widgets by name -- this ought to become something else that better considers plugin extensibility.

  var widgets = Object.create(null);
  for (var k in widgets_appui) {
    widgets[k] = widgets_appui[k];
  }
  for (var k in widgets_basic) {
    widgets[k] = widgets_basic[k];
  }
  for (var k in widgets_dbui) {
    widgets[k] = widgets_dbui[k];
  }
  for (var k in widgets_spectrum) {
    widgets[k] = widgets_spectrum[k];
  }
  
  // TODO: This is currently used by plugins to extend the widget namespace. Create a non-single-namespace widget type lookup and then freeze this.
  return widgets;
});
