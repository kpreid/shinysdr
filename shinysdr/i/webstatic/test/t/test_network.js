// Copyright 2019 Kevin Reid and the ShinySDR contributors
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
  '/test/testutil.js',
  'client-configuration-module',
  'events',
  'network',
  'types',
  'values',
], (
  import_jasmine,
  import_testutil,
  import_client_configuration,
  import_events,
  import_network,
  import_types,
  import_values
) => {
  const {ji: {
    describe,
    expect,
    it,
    jasmine
  }} = import_jasmine;
  const {
  } = import_testutil;
  const {
    getSharedTestObjectsURL,
  } = import_client_configuration;
  const {
    Scheduler,
  } = import_events;
  const {
    connect,
  } = import_network;
  const {
    anyT,
  } = import_types;
  const {
    ConstantCell,
    makeBlock
  } = import_values;
  
  const CAP_OBJECT_PATH_ELEMENT = 'radio';  // TODO get from server
  
  describe('network', () => {
    describe('connect', () => {
      it('should successfully connect to the test endpoint', done => {
        const scheduler = new Scheduler();
        const rootCell = connect(getSharedTestObjectsURL());
        rootCell.n.listen(scheduler.claim(() => {
          expect(rootCell.get()).toBeTruthy();
          done();
        }));
      });
    });
  });
  
  return 'ok';
});