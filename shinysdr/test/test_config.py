# Copyright 2014 Kevin Reid <kpreid@switchb.org>
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

'''
See also test_main.py.
'''

from __future__ import absolute_import, division

import os.path
import shutil
import tempfile

from twisted.internet import reactor
from twisted.trial import unittest

from shinysdr import config
from shinysdr import devices
from shinysdr.values import nullExportedState


def StubDevice():
    '''Return a valid trivial device.'''
    return devices.Device(components={u'c': nullExportedState})


class TestConfigObject(unittest.TestCase):
    def setUp(self):
        self.config = config.Config(reactor)
    
    # TODO: In type error tests, also check message once we've cleaned them up.
    
    def test_device_key_ok(self):
        dev = StubDevice()
        self.config.devices.add(u'foo', dev)
        self.assertEqual({u'foo': dev}, self.config.devices._values)
        self.assertEqual(unicode, type(self.config.devices._values.keys()[0]))
    
    def test_device_key_string_ok(self):
        dev = StubDevice()
        self.config.devices.add('foo', dev)
        self.assertEqual({u'foo': dev}, self.config.devices._values)
        self.assertEqual(unicode, type(self.config.devices._values.keys()[0]))
    
    def test_device_key_type(self):
        self.assertRaises(TypeError, lambda:
            self.config.devices.add(StubDevice(), StubDevice()))
        self.assertEqual({}, self.config.devices._values)
    
    def test_device_key_duplication(self):
        dev = StubDevice()
        self.config.devices.add(u'foo', dev)
        self.assertRaises(KeyError, lambda:
            self.config.devices.add(u'foo', StubDevice()))
        self.assertEqual({u'foo': dev}, self.config.devices._values)
    
    def test_device_empty(self):
        self.assertRaises(ValueError, lambda:
            self.config.devices.add(u'foo'))
        self.assertEqual({}, self.config.devices._values)
    
    def test_web_root_cap_empty(self):
        self.assertRaises(ValueError, lambda:
            self.config.serve_web(http_endpoint='tcp:8100', ws_endpoint='tcp:8101', root_cap=''))
        self.assertEqual([], self.config._service_makers)
    


class TestDefaultConfig(unittest.TestCase):
    def setUp(self):
        self.__temp_dir = tempfile.mkdtemp(prefix='shinysdr_test_config_tmp')
        self.__config_name = os.path.join(self.__temp_dir, 'config')
    
    def tearDown(self):
        shutil.rmtree(self.__temp_dir)
    
    def test_default_config(self):
        conf_text = config.make_default_config()
        
        # Don't try to open a real device
        DEFAULT_DEVICE = "OsmoSDRDevice('')"
        self.assertIn(DEFAULT_DEVICE, conf_text)
        conf_text = conf_text.replace(DEFAULT_DEVICE, "OsmoSDRDevice('file=/dev/null,rate=100000')")
        
        with open(self.__config_name, 'w') as f:
            f.write(conf_text)
        config_obj = config.Config(reactor)
        config.execute_config(config_obj, self.__config_name)
        return config_obj._wait_and_validate()
