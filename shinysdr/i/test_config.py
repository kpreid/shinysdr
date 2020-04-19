# -*- coding: utf-8 -*-
# Copyright 2014, 2015, 2016, 2018, 2019, 2020 Kevin Reid and the ShinySDR contributors
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

from __future__ import absolute_import, division, print_function, unicode_literals

import os.path
import sys
import textwrap

import six

from twisted.internet import reactor as the_reactor
from twisted.internet import defer
from twisted.logger import Logger
from twisted.trial import unittest
from zope.interface import implementer

from shinysdr import devices
from shinysdr.i.config import Config, ConfigException, ConfigTooLateException, execute_config, print_config_exception, write_default_config
from shinysdr.i.roots import IEntryPoint
from shinysdr.testutil import Files, LogTester, StubRXDriver
from shinysdr.values import ExportedState


NO_NETWORK = dict(log_format='No network service defined!')


class TestConfigObject(unittest.TestCase):
    def setUp(self):
        self.log_tester = LogTester()
        self.config = ConfigFactory(log=self.log_tester.log)
    
    def complete_minimally(self):
        self.config.devices.add(u'stub_for_completion', StubDevice())
    
    # TODO: In type error tests, also check message once we've cleaned them up.
    
    # --- General functionality ---
    
    def test_reactor(self):
        self.assertEqual(self.config.reactor, the_reactor)
    
    # TODO def test_wait_for(self):
    
    @defer.inlineCallbacks
    def test_validate_succeed(self):
        self.complete_minimally()
        d = self.config._wait_and_validate()
        self.assertIsInstance(d, defer.Deferred)  # don't succeed trivially
        yield d
    
    @defer.inlineCallbacks
    def test_no_network_service(self):
        self.complete_minimally()
        yield self.config._wait_and_validate()
        self.log_tester.check(NO_NETWORK)
    
    @defer.inlineCallbacks
    def test_no_devices(self):
        yield self.assertFailure(self.config._wait_and_validate(), ConfigException)

    # --- Persistence ---
    
    @defer.inlineCallbacks
    def test_persist_too_late(self):
        self.complete_minimally()
        yield self.config._wait_and_validate()
        self.assertRaises(ConfigTooLateException, lambda:
            self.config.persist_to_file('foo'))
        self.assertEqual(None, self.config._state_filename)
    
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
        self.complete_minimally()
        yield self.config._wait_and_validate()
        self.assertRaises(ConfigTooLateException, lambda:
            self.config.devices.add(u'foo', StubDevice()))
        self.assertEqual(['stub_for_completion'], list(self.config.devices._values.keys()))
    
    def test_device_key_ok(self):
        dev = StubDevice()
        self.config.devices.add(u'foo', dev)
        self.assertEqual({u'foo': dev}, self.config.devices._values)
        self.assertEqual(six.text_type, type(first(self.config.devices._values)))
    
    def test_device_key_string_ok(self):
        dev = StubDevice()
        self.config.devices.add('foo', dev)
        self.assertEqual({u'foo': dev}, self.config.devices._values)
        self.assertEqual(six.text_type, type(first(self.config.devices._values)))
    
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
        self.complete_minimally()
        yield self.config._wait_and_validate()
        self.assertRaises(ConfigTooLateException, lambda:
            self.config.serve_web(http_endpoint='tcp:8100', ws_endpoint='tcp:8101'))
        self.assertEqual([], self.config._service_makers)
    
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
        service = self.config._service_makers[0](DummyAppRoot())
        self.assertEqual('/public/', service.get_host_relative_url())
    
    def test_web_base_url_invalid_scheme(self):
        e = self.assertRaises(ConfigException, lambda:
            self.config.serve_web(http_endpoint='tcp:0', ws_endpoint='tcp:0', http_base_url='flibbertigibbet'))
        self.assertEqual("config.serve_web: http_base_url must be a 'http:' or 'https:' URL but was 'flibbertigibbet'", str(e))
        
        e = self.assertRaises(ConfigException, lambda:
            self.config.serve_web(http_endpoint='tcp:0', ws_endpoint='tcp:0', ws_base_url='flibbertigibbet'))
        self.assertEqual("config.serve_web: ws_base_url must be a 'ws:' or 'wss:' URL but was 'flibbertigibbet'", str(e))
        
        self.assertEqual([], self.config._service_makers)
        
    def test_web_base_url_http_prohibits_path(self):
        e = self.assertRaises(ConfigException, lambda:
            self.config.serve_web(http_endpoint='tcp:0', ws_endpoint='tcp:0', http_base_url='https://shinysdr.test/flibbertigibbet/'))
        self.assertEqual("config.serve_web: http_base_url must not have any path components, but had '/flibbertigibbet/'", str(e))
        
    def test_web_base_url_ws_allows_path(self):
        self.config.serve_web(http_endpoint='tcp:0', ws_endpoint='tcp:0', ws_base_url='wss://shinysdr.test/flibbertigibbet/')
        self.assertEqual(1, len(self.config._service_makers))
        # TODO: Actually validate the resulting path generation (hard to get at unless we add a method)
        
    def test_web_base_url_ws_requires_slash(self):
        e = self.assertRaises(ConfigException, lambda:
            self.config.serve_web(http_endpoint='tcp:0', ws_endpoint='tcp:0', ws_base_url='wss://shinysdr.test/flibbertigibbet'))
        self.assertEqual("config.serve_web: ws_base_url's path must end in a slash, but had '/flibbertigibbet'", str(e))
        
    def test_web_base_url_http_root(self):
        self.config.serve_web(http_endpoint='tcp:0', ws_endpoint='tcp:0', http_base_url='https://shinysdr.test:1234/')
        self.assertEqual(1, len(self.config._service_makers))
        # Actually instantiating the service to find out what its url is.
        service = self.config._service_makers[0](DummyAppRoot())
        self.assertEqual('https://shinysdr.test:1234/public/', service.get_url())
        self.assertEqual('/public/', service.get_host_relative_url())
    
    # --- serve_ghpsdr ---
    
    @defer.inlineCallbacks
    def test_ghpsdr_too_late(self):
        self.complete_minimally()
        yield self.config._wait_and_validate()
        self.assertRaises(ConfigTooLateException, lambda:
            self.config.serve_ghpsdr())
        self.assertEqual([], self.config._service_makers)
    
    def test_ghpsdr_ok(self):
        self.config.serve_ghpsdr()
        self.assertEqual(1, len(self.config._service_makers))
    
    # --- Misc options ---
    
    @defer.inlineCallbacks
    def test_server_audio_too_late(self):
        self.complete_minimally()
        yield self.config._wait_and_validate()
        self.assertRaises(ConfigTooLateException, lambda:
            self.config.set_server_audio_allowed(True))
    
    # TODO test rest of config.set_server_audio_allowed

    @defer.inlineCallbacks
    def test_stereo_too_late(self):
        self.complete_minimally()
        yield self.config._wait_and_validate()
        self.assertRaises(ConfigTooLateException, lambda:
            self.config.set_stereo(False))
        self.assertTrue(self.config.features._get('stereo'))
    
    # TODO test rest of config.set_stereo
    
    # --- Features ---
    
    def test_features_unknown(self):
        self.assertRaises(ConfigException, lambda:
            self.config.features.enable('bogus'))
        self.assertFalse('bogus' in self.config.features._state)
    
    @defer.inlineCallbacks
    def test_features_enable_too_late(self):
        self.complete_minimally()
        yield self.config._wait_and_validate()
        self.assertRaises(ConfigTooLateException, lambda:
            self.config.features.enable('_test_disabled_feature'))
        self.assertFalse(self.config.features._get('_test_disabled_feature'))
    
    @defer.inlineCallbacks
    def test_features_disable_too_late(self):
        self.complete_minimally()
        yield self.config._wait_and_validate()
        self.assertRaises(ConfigTooLateException, lambda:
            self.config.features.enable('_test_enabled_feature'))
        self.assertTrue(self.config.features._get('_test_enabled_feature'))
    
    # --- Databases ---
    # Tests of database configuration may be found in TestConfigFiles.


class TestConfigFiles(unittest.TestCase):
    def setUp(self):
        self.__files = Files({})
        self.__config_name = os.path.join(self.__files.dir, 'config')
        self.log_tester = LogTester()
        self.__config = ConfigFactory(log=self.log_tester.log)
    
    def tearDown(self):
        self.__files.close()
    
    def __dirpath(self, *paths):
        return os.path.join(self.__config_name, *paths)
    
    def test_config_file(self):
        self.__files.create({
            self.__config_name: 'config.features.enable("_test_disabled_feature")',
            'dbs': {
                # DB CSV file we expect NOT to be loaded
                'foo.csv': 'Frequency,Name',
            },
        })

        execute_config(self.__config, self.__config_name)
        
        # Config python was executed
        self.assertTrue(self.__config.features._get('_test_disabled_feature'))
        
        # Config-directory-related defaults were not set
        self.assertEqual(None, self.__config._state_filename)
        self.assertEqual(six.viewkeys(get_default_dbs()), six.viewkeys(self.__config.databases._get_read_only_databases()))
    
    def test_config_file_is_unicode_clean(self):
        self.__files.create({
            self.__config_name: textwrap.dedent("""\
                # -*- coding: utf-8 -*-
                from shinysdr.i.test_config import StubDevice
                config.devices.add(u'•', StubDevice())
            """),
        })

        execute_config(self.__config, self.__config_name)
        self.assertEqual({u'•'}, set(self.__config.devices._values.keys()))
    
    def test_config_directory(self):
        self.__files.create({
            self.__config_name: {
                'config.py': 'config.features.enable("_test_disabled_feature")',
                'dbs-read-only': {
                    'foo.csv': 'Frequency,Name',
                },
            },
        })
        execute_config(self.__config, self.__config_name)
        
        # Config python was executed
        self.assertTrue(self.__config.features._get('_test_disabled_feature'))
        
        # Config-directory-related defaults were set
        self.assertEqual(self.__dirpath('state.json'), self.__config._state_filename)
        self.assertIn('foo.csv', self.__config.databases._get_read_only_databases())
    
    def test_default_config(self):
        write_default_config(self.__config_name)
        self.assertTrue(os.path.isdir(self.__config_name))
        
        # Don't try to open a real device
        with open(self.__dirpath('config.py'), 'r') as f:
            conf_text = f.read()
        DEFAULT_DEVICE = "OsmoSDRDevice('')"
        self.assertIn(DEFAULT_DEVICE, conf_text)
        conf_text = conf_text.replace(DEFAULT_DEVICE, "OsmoSDRDevice('file=/dev/null,rate=100000')")
        with open(self.__dirpath('config.py'), 'w') as f:
            f.write(conf_text)
        
        execute_config(self.__config, self.__config_name)
        
        self.assertTrue(os.path.isdir(self.__dirpath('dbs-read-only')))
        return self.__config._wait_and_validate()
    
    def test_traceback_processing(self):
        self.maxDiff = 1000
        self.__files.create({
            self.__config_name: 'config.devices.add("will-fail")'
        })
        file_obj = six.StringIO()
        try:
            execute_config(self.__config, self.__config_name)
            self.fail('did not raise')
        except ConfigException:
            print_config_exception(sys.exc_info(), file_obj)
        self.assertEqual(
            file_obj.getvalue()
            .replace(self.__files.dir, '<tempdir>')
            .replace(__file__, '<config.py>'),
            textwrap.dedent("""\
                An error occurred while executing the ShinySDR configuration file:
                  File "<tempdir>/config", line 1, in <module>
                    config.devices.add("will-fail")
                ConfigException: config.devices.add: no device(s) specified
            """))
    
    # --- Databases ---
    # These are really tests of the config object, but database processing uses files.
    
    # TODO more tests of config.databases.add_directory
    # TODO more tests of config.databases.add_writable_database
    
    @defer.inlineCallbacks
    def test_db_content_warning(self):
        self.__files.create({
            self.__config_name: {
                'config.py': '',
                'dbs-read-only': {
                    'foo.csv': 'Name\na',
                },
            },
        })
        execute_config(self.__config, self.__config_name)
        self.__config.devices.add(u'stub_for_completion', StubDevice())
        yield self.__config._wait_and_validate()
        self.log_tester.check(
            dict(log_format='{path}: {db_diagnostic}', path='foo.csv'),
            NO_NETWORK)


def StubDevice():
    """Return a valid trivial device."""
    return devices.Device(rx_driver=StubRXDriver(), components={})


def ConfigFactory(log=Logger()):
    return Config(the_reactor, log)


def get_default_dbs():
    config_obj = ConfigFactory()
    return config_obj.databases._get_read_only_databases()


class DummyAppRoot(ExportedState):
    def get_session(self):
        return StubEntryPoint()
    
    def get_receive_flowgraph(self):
        return None


@implementer(IEntryPoint)
class StubEntryPoint(object):
    def entry_point_is_deleted(self):
        return False


def first(iterable):
    for x in iterable:
        return x
