# Copyright 2014, 2015, 2016 Kevin Reid <kpreid@switchb.org>
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

from twisted.trial import unittest
from twisted.internet import defer, reactor

from shinysdr.plugins.hamlib import connect_to_rig, connect_to_rotator
from shinysdr.test.testutil import state_smoke_test


class TestHamlibRig(unittest.TestCase):
    """
    Also contains generic proxy tests.
    """
    timeout = 5
    __rig = None
    
    def setUp(self):
        d = connect_to_rig(reactor, options=['-m', '1'], port=4530)
        
        def on_connect(rig_device):
            self.__rig = rig_device.get_components_dict()['rig']
        
        # pylint: disable=no-member
        d.addCallback(on_connect)
        return d
    
    def tearDown(self):
        return self.__rig.close()
    
    def test_noop(self):
        """basic connect and disconnect, check is clean"""
        pass

    @defer.inlineCallbacks
    def test_state_smoke(self):
        state_smoke_test(self.__rig)
        yield self.__rig.sync()
        state_smoke_test(self.__rig)
    
    @defer.inlineCallbacks
    def test_getter(self):
        yield self.__rig.sync()
        self.assertEqual(self.__rig.state()['freq'].get(), 145e6)

    @defer.inlineCallbacks
    def test_setter(self):
        yield self.__rig.sync()
        self.__rig.state()['freq'].set(123e6)
        yield self.__rig.sync()
        self.assertEqual(self.__rig.state()['freq'].get(), 123e6)

    @defer.inlineCallbacks
    def test_sync(self):
        yield self.__rig.sync()
        yield self.__rig.sync()


class TestHamlibRotator(unittest.TestCase):
    timeout = 5
    __rotator = None
    
    def setUp(self):
        d = connect_to_rotator(reactor, options=['-m', '1'], port=4531)
        
        def on_connect(rotator_device):
            self.__rotator = rotator_device.get_components_dict()['rotator']
        
        # pylint: disable=no-member
        d.addCallback(on_connect)
        return d
    
    def tearDown(self):
        return self.__rotator.close()
    
    def test_noop(self):
        """basic connect and disconnect, check is clean"""
        pass
