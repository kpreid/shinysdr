# -*- coding: utf-8 -*-
# Copyright 2016 Kevin Reid <kpreid@switchb.org>
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

from __future__ import absolute_import, division, unicode_literals

from twisted.test.proto_helpers import StringTransport
from twisted.trial import unittest
from twisted.internet import defer
from twisted.internet.interfaces import IStreamClientEndpoint
from twisted.internet import reactor as the_reactor
from zope.interface import implementer

from shinysdr.plugins.controller import Controller, Command, Selector
from shinysdr.test.testutil import state_smoke_test
from shinysdr.types import EnumT


class TestController(unittest.TestCase):
    """
    Also contains generic proxy tests.
    """
    timeout = 5
    
    def setUp(self):
        self.endpoint = _StringEndpoint()
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
        self.assertEqual('cmd_text', self.endpoint.t.value())
    
    def test_send_enum(self):
        self.proxy.state()['enum_name'].set('enum_text1')
        self.endpoint.t.clear()
        self.proxy.state()['enum_name'].set('enum_text2')
        self.assertEqual('enum_text2', self.endpoint.t.value())
    
    def test_encode_command(self):
        self.proxy.state()['unicode_cmd'].set(True)  # TODO command-cell kludge
        self.assertEqual(u'façade'.encode('UTF-8'), self.endpoint.t.value())
    
    def test_encode_enum(self):
        self.proxy.state()['enum_name'].set(u'façade')
        self.assertEqual(u'façade'.encode('UTF-8'), self.endpoint.t.value())


@implementer(IStreamClientEndpoint)
class _StringEndpoint(object):
    def __init__(self):
        self.t = StringTransport()
    
    def connect(self, protocol_factory):
        protocol = protocol_factory.buildProtocol(None)
        protocol.makeConnection(self.t)
        return defer.succeed(protocol)
