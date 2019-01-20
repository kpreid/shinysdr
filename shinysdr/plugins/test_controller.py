# -*- coding: utf-8 -*-
# Copyright 2016, 2018 Kevin Reid and the ShinySDR contributors
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

from twisted.trial import unittest
from twisted.internet import defer
from twisted.internet import reactor as the_reactor

from shinysdr.plugins.controller import Controller, Command, Selector
from shinysdr.testutil import StringTransportEndpoint, state_smoke_test
from shinysdr.types import EnumT


class TestController(unittest.TestCase):
    """
    Also contains generic proxy tests.
    """
    timeout = 5
    
    def setUp(self):
        self.endpoint = StringTransportEndpoint()
        self.t = self.endpoint.string_transport
        self.device = Controller(
            reactor=the_reactor,
            endpoint=self.endpoint,
            elements=[
                Command('cmd_name', 'cmd_text'),
                Command('unicode_cmd', u'façade'),
                Selector('enum_name', EnumT({u'enum_text1': u'enum_label1', u'enum_text2': u'enum_label2'}, strict=False))
            ],
            encoding='UTF-8')
        self.proxy = self.device.get_components_dict()['controller']
    
    @defer.inlineCallbacks
    def tearDown(self):
        yield self.device.close()
        yield self.proxy.close()  # TODO kludge because device close doesn't actually work for our purposes
    
    def test_state_smoke(self):
        state_smoke_test(self.device)
    
    def test_send_command(self):
        self.proxy.state()['cmd_name'].set(True)  # TODO command-cell kludge
        self.assertEqual(b'cmd_text', self.t.value())
    
    def test_send_enum(self):
        self.proxy.state()['enum_name'].set('enum_text1')
        self.t.clear()
        self.proxy.state()['enum_name'].set('enum_text2')
        self.assertEqual(b'enum_text2', self.t.value())
    
    def test_encode_command(self):
        self.proxy.state()['unicode_cmd'].set(True)  # TODO command-cell kludge
        self.assertEqual(u'façade'.encode('UTF-8'), self.t.value())
    
    def test_encode_enum(self):
        self.proxy.state()['enum_name'].set(u'façade')
        self.assertEqual(u'façade'.encode('UTF-8'), self.t.value())
