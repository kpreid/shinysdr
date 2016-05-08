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

"""
See also test_main.py.
"""

from __future__ import absolute_import, division

import os.path
import shutil
import tempfile

from twisted.internet import reactor as the_reactor
from twisted.internet import defer
from twisted.trial import unittest

from shinysdr import devices
from shinysdr.config import Config, ConfigException, ConfigTooLateException, execute_config, make_default_config
from shinysdr.values import ExportedState, nullExportedState


def StubDevice():
    """Return a valid trivial device."""
    return devices.Device(components={u'c': nullExportedState})


class TestConfigObject(unittest.TestCase):
    def setUp(self):
        self.config = Config(the_reactor)
    
    # TODO: In type error tests, also check message once we've cleaned them up.
    
    # --- General functionality ---
    
    def test_reactor(self):
        self.assertEqual(self.config.reactor, the_reactor)
    
    # TODO def test_wait_for(self):
    
    @defer.inlineCallbacks
    def test_validate_succeed(self):
        self.config.devices.add(u'foo', StubDevice())
        d = self.config._wait_and_validate()
        self.assertIsInstance(d, defer.Deferred)  # don't succeed trivially
        yield d
    
    # TODO: Test "No network service defined"; is a warning not an error

    # --- Persistence ---
    
    @defer.inlineCallbacks
    def test_persist_too_late(self):
        yield self.config._wait_and_validate()
        self.assertRaises(ConfigTooLateException, lambda:
            self.config.persist_to_file('foo'))
        self.assertEqual({}, self.config.devices._values)
    
    def test_persist_none(self):
        self.assertEqual(None, self.config._state_filename)

    def test_persist_ok(self):
        self.config.persist_to_file('foo')
        self.assertEqual('foo', self.config._state_filename)

    def test_persist_duplication(self):
        self.config.persist_to_file('foo')
        self.assertRaises(ConfigException, lambda: self.config.persist_to_file('bar'))
        self.assertEqual('foo', self.config._state_filename)

    # --- Devices ---
    
    @defer.inlineCallbacks
    def test_device_too_late(self):
        yield self.config._wait_and_validate()
        self.assertRaises(ConfigTooLateException, lambda:
            self.config.devices.add(u'foo', StubDevice()))
        self.assertEqual({}, self.config.devices._values)
    
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
        self.assertRaises(ConfigException, lambda:
            self.config.devices.add(StubDevice(), StubDevice()))
        self.assertEqual({}, self.config.devices._values)
    
    def test_device_key_duplication(self):
        dev = StubDevice()
        self.config.devices.add(u'foo', dev)
        self.assertRaises(ConfigException, lambda:
            self.config.devices.add(u'foo', StubDevice()))
        self.assertEqual({u'foo': dev}, self.config.devices._values)
    
    def test_device_empty(self):
        self.assertRaises(ConfigException, lambda:
            self.config.devices.add(u'foo'))
        self.assertEqual({}, self.config.devices._values)
    
    # --- serve_web ---
    
    @defer.inlineCallbacks
    def test_web_too_late(self):
        yield self.config._wait_and_validate()
        self.assertRaises(ConfigTooLateException, lambda:
            self.config.serve_web(http_endpoint='tcp:8100', ws_endpoint='tcp:8101'))
        self.assertEqual({}, self.config.devices._values)
    
    def test_web_ok(self):
        self.config.serve_web(http_endpoint='tcp:8100', ws_endpoint='tcp:8101')
        self.assertEqual(1, len(self.config._service_makers))
    
    def test_web_root_cap_empty(self):
        self.assertRaises(ConfigException, lambda:
            self.config.serve_web(http_endpoint='tcp:8100', ws_endpoint='tcp:8101', root_cap=''))
        self.assertEqual([], self.config._service_makers)
    
    def test_web_root_cap_none(self):
        self.config.serve_web(http_endpoint='tcp:0', ws_endpoint='tcp:0')
        self.assertEqual(1, len(self.config._service_makers))
        # Actually instantiating the service. We need to do this to check if the root_cap value was processed correctly.
        service = self.config._service_makers[0](DummyAppRoot(), lambda: None)
        self.assertEqual('/', service.get_host_relative_url())
    
    # --- serve_ghpsdr ---
    
    @defer.inlineCallbacks
    def test_ghpsdr_too_late(self):
        yield self.config._wait_and_validate()
        self.assertRaises(ConfigTooLateException, lambda:
            self.config.serve_ghpsdr())
        self.assertEqual({}, self.config.devices._values)
    
    def test_ghpsdr_ok(self):
        self.config.serve_ghpsdr()
        self.assertEqual(1, len(self.config._service_makers))
    
    # --- Misc options ---
    
    @defer.inlineCallbacks
    def test_server_audio_too_late(self):
        yield self.config._wait_and_validate()
        self.assertRaises(ConfigTooLateException, lambda:
            self.config.set_server_audio_allowed(True))
        self.assertEqual({}, self.config.devices._values)
    
    # TODO test rest of config.set_server_audio_allowed

    @defer.inlineCallbacks
    def test_stereo_too_late(self):
        yield self.config._wait_and_validate()
        self.assertRaises(ConfigTooLateException, lambda:
            self.config.set_stereo(True))
        self.assertEqual({}, self.config.devices._values)
    
    # TODO test rest of config.set_stereo
    
    # --- Databases ---
    
    # TODO test config.databases.add_directory
    # TODO test config.databases.add_writable_database
    

class TestDefaultConfig(unittest.TestCase):
    def setUp(self):
        self.__temp_dir = tempfile.mkdtemp(prefix='shinysdr_test_config_tmp')
        self.__config_name = os.path.join(self.__temp_dir, 'config')
    
    def tearDown(self):
        shutil.rmtree(self.__temp_dir)
    
    def test_default_config(self):
        conf_text = make_default_config()
        
        # Don't try to open a real device
        DEFAULT_DEVICE = "OsmoSDRDevice('')"
        self.assertIn(DEFAULT_DEVICE, conf_text)
        conf_text = conf_text.replace(DEFAULT_DEVICE, "OsmoSDRDevice('file=/dev/null,rate=100000')")
        
        with open(self.__config_name, 'w') as f:
            f.write(conf_text)
        config_obj = Config(the_reactor)
        execute_config(config_obj, self.__config_name)
        return config_obj._wait_and_validate()


class DummyAppRoot(ExportedState):
    def get_session(self):
        return self
    
    def get_receive_flowgraph(self):
        return None