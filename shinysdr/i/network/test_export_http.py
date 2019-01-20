# -*- coding: utf-8 -*-
# Copyright 2017 Kevin Reid and the ShinySDR contributors
# 
# This file is part of ShinySDR.
# 
# ShinySDR is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
# 
# ShinySDR is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with ShinySDR.  If not, see <http://www.gnu.org/licenses/>.

from __future__ import absolute_import, division, print_function, unicode_literals

import json

from twisted.internet import defer
from twisted.internet import reactor as the_reactor
from twisted.trial import unittest

from shinysdr.i.network.base import SiteWithDefaultHeaders, WebServiceCommon
from shinysdr.i.network.export_http import BlockResource
from shinysdr.testutil import assert_http_resource_properties, http_get, http_request
from shinysdr.values import ExportedState, exported_value, setter


class TestBlockTreeResources(unittest.TestCase):
    # TODO: Have less boilerplate "set up a web server".
    
    def setUp(self):
        wcommon = WebServiceCommon.stub(reactor=the_reactor)
        self.obj = StateSpecimen()
        r = BlockResource(self.obj, wcommon, None)
        self.port = the_reactor.listenTCP(0, SiteWithDefaultHeaders(r), interface="127.0.0.1")  # pylint: disable=no-member

    def tearDown(self):
        return self.port.stopListening()

    def __url(self, path):
        return 'http://127.0.0.1:%i%s' % (self.port.getHost().port, path)

    def test_leaf_cell_common(self):
        return assert_http_resource_properties(self, self.__url('/leaf_cell'))
    
    @defer.inlineCallbacks
    def test_leaf_cell_get(self):
        response, data = yield http_get(the_reactor, self.__url('/leaf_cell'))
        self.assertEqual(response.headers.getRawHeaders('Content-Type'), ['application/json'])
        self.assertEqual([1, 2, 3], json.loads(data))
    
    @defer.inlineCallbacks
    def test_leaf_cell_put(self):
        yield http_request(the_reactor, self.__url('/leaf_cell'),
            method='PUT',
            body='[3, 4, 5]')
        
        response, data = yield http_get(the_reactor, self.__url('/leaf_cell'))
        self.assertEqual(response.headers.getRawHeaders('Content-Type'), ['application/json'])
        self.assertEqual([3, 4, 5], json.loads(data))
    
    # TODO: test BlockResource behavior rather than just the leaf


class StateSpecimen(ExportedState):
    """Helper for TestBlockTreeResources"""

    def __init__(self):
        self.value = [1, 2, 3]
    
    @exported_value(type=list, changes='this_setter')
    def get_leaf_cell(self):
        return self.value
    
    @setter
    def set_leaf_cell(self, value):
        self.value = value
