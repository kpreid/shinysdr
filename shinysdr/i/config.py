# Copyright 2013, 2014, 2015, 2016, 2017, 2018, 2020 Kevin Reid and the ShinySDR contributors
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
Config interface and config directory management.

The "public" operations on these objects are used by configuration files to specify configuration. The "private" operations are then used by main.py to implement the configuration.
"""


from __future__ import absolute_import, division, print_function, unicode_literals

import importlib
import os
import os.path
import traceback

import six
from six.moves import builtins

from twisted.internet import defer
from twisted.python.util import sibpath
from twisted.web.http import urlparse

# Note that gnuradio-dependent modules are loaded lazily, to avoid the startup time if all we're going to do is give a usage message
from shinysdr.i.db import DatabaseModel, database_from_csv, databases_from_directory
from shinysdr.i.network.base import UNIQUE_PUBLIC_CAP
from shinysdr.i.pycompat import bytes_or_ascii, repr_no_string_tag
from shinysdr.i.roots import CapTable, generate_cap


__all__ = []  # appended later


class Config(object):
    def __init__(self, reactor, log):
        self.__log = log
        
        # public config elements
        self.features = _ConfigFeatures(self)
        self.devices = _ConfigDevices(self)
        self.sources = self.devices  # temporary legacy compat -- TODO emit deprecation warnings or something, then remove
        self.databases = _ConfigDbs(self, reactor, self.__log)

        # provided for the convenience of the config file
        self.reactor = reactor
        
        # these are to be read by main
        self._state_filename = None
        self._service_makers = []
        
        # private: config state
        self.__server_audio = None
        
        # private: meta
        self.__waiting = []
        self.__finished = False
    
    @defer.inlineCallbacks
    def _wait_and_validate(self):
        """After all config.wait_for() complete, validate that the configuration is valid."""
        # TODO: Make this method idempotent. (This requires introducing the state "in the middle of waiting", midway between not-finished and finished.) For now, it is expected to be called only once.
        
        yield defer.gatherResults(self.__waiting)
        
        # reboot used to be not-a-plugin so we have this hardcoded definition -- but exposing the plugin isn't necessarily a good replacement anyway
        if self.features._get('reboot'):
            from shinysdr.plugins.rebooter import Rebooter
            self.devices.add('rebooter', Rebooter(self.reactor))
        
        self.__finished = True
        
        self.features._validate()
        self.devices._validate()
        self.databases._validate()
        
        if len(self._service_makers) == 0:
            self.__log.warn('No network service defined!')
    
    def _create_app(self):
        from shinysdr.i.session import AppRoot
        return AppRoot(
            devices=self.devices._values,
            audio_config=self.__server_audio,
            read_only_dbs=self.databases._get_read_only_databases(),
            writable_db=self.databases._get_writable_database(),
            features=self.features._get_all())
    
    def _not_finished(self):
        if self.__finished:
            raise ConfigTooLateException()
    
    def wait_for(self, deferred):
        """Wait for the provided Deferred before assuming the configuration to be finished."""
        self._not_finished()
        self.__waiting.append(defer.maybeDeferred(lambda: deferred))
    
    def persist_to_file(self, filename):
        self._not_finished()
        if self._state_filename is not None:
            raise ConfigException('config.persist_to_file has already been done once')
        self._state_filename = str(filename)

    def serve_web(self, 
            http_endpoint,
            ws_endpoint,
            http_base_url=None,
            ws_base_url=None,
            root_cap=None,
            title=u'ShinySDR'):
        self._not_finished()
        # TODO: See if we're reinventing bits of Twisted service stuff here
        
        http_base_url = _coerce_and_validate_base_url(http_base_url, 'http_base_url', ('http', 'https'))
        ws_base_url = _coerce_and_validate_base_url(ws_base_url, 'ws_base_url', ('ws', 'wss'))
        
        if root_cap is not None:
            root_cap = six.text_type(root_cap)
            if len(root_cap) <= 0:
                raise ConfigException('config.serve_web: root_cap must be None or a nonempty string')
        
        def make_service(app):
            # TODO: Temporary glue while we refactor for multisession
            session = app.get_session()
            cap_table = CapTable(lambda bogus: bogus)
            if root_cap is None:
                cap_table.add(session, cap=UNIQUE_PUBLIC_CAP)
                root_cap_subst = UNIQUE_PUBLIC_CAP
            else:
                cap_table.add(session, cap=root_cap)
                root_cap_subst = root_cap
            
            from shinysdr.i.network.webapp import WebService
            return WebService(
                reactor=self.reactor,
                cap_table=cap_table.as_unenumerable_collection(),
                http_endpoint=http_endpoint,
                ws_endpoint=ws_endpoint,
                http_base_url=http_base_url,
                ws_base_url=ws_base_url,
                root_cap=root_cap_subst,
                title=title)
        
        self._service_makers.append(make_service)

    def serve_ghpsdr(self):
        self._not_finished()
        # TODO: Alternate services should be provided using getPlugins rather than hardcoded
        
        def make_service(app):
            import shinysdr.plugins.ghpsdr as lazy_ghpsdr
            return lazy_ghpsdr.DspserverService(self.reactor, app.get_receive_flowgraph(), 'tcp:8000')
        
        self._service_makers.append(make_service)
    
    def set_server_audio_allowed(self, allowed, device_name='', sample_rate=44100):
        """
        Set whether clients are allowed to send output to the server audio device.
        """
        self._not_finished()
        
        if allowed:
            self.__server_audio = (str(device_name), int(sample_rate))
        else:
            self.__server_audio = None
    
    def set_stereo(self, value):
        """
        Deprecated alias for self.features.(en|dis)able('stereo').
        """
        if value:
            self.features.enable('stereo')
        else:
            self.features.disable('stereo')


__all__.append('Config')


def _coerce_and_validate_base_url(url_value, label, allowed_schemes):
    """Convert url_value to string or None and validate it is a suitable base URL."""
    if url_value is not None:
        url_value = str(url_value)
        
        scheme, _netloc, path_bytes, _params, _query_bytes, _fragment = urlparse(bytes_or_ascii(url_value))
        if scheme.lower() not in allowed_schemes:
            raise ConfigException('config.serve_web: {} must be a {} URL but was {}'.format(label, ' or '.join(repr_no_string_tag(s + ':') for s in allowed_schemes), repr_no_string_tag(url_value)))
        if path_bytes != b'/':
            raise ConfigException('config.serve_web: {} must not have any path components, but had {}'.format(label, repr_no_string_tag(path_bytes)))
    
    return url_value


class _ConfigDict(object):
    def __init__(self, config):
        self._values = {}
        self._config = config

    def add(self, key, value):
        self._config._not_finished()
        if not isinstance(key, six.string_types):
            # Used to just coerce, but I saw a user error where they did "config.devices.add(device)", so I figured an error is better
            raise ConfigException('Key must be a string, not a %s: %r' % (type(key), key))
        key = six.text_type(key)
        if key in self._values:
            raise ConfigException('Key %r already present' % (key,))
        self._values[key] = value
    
    def _validate(self):
        """Check that the configuration is consistent and raise ConfigException if not."""


class _ConfigDevices(_ConfigDict):
    def add(self, key, *devices):
        # pylint: disable=arguments-differ
        if len(devices) <= 0:
            raise ConfigException('config.devices.add: no device(s) specified')
        from shinysdr.devices import merge_devices
        super(_ConfigDevices, self).add(key, merge_devices(devices))
    
    def _validate(self):
        super(_ConfigDevices, self)._validate()
        
        # Ensure there is at least one device. (This restriction is due to the current implementation of shinysdr.i.top.Top and should be eliminated when practical.)
        for device in self._values.values():
            if device.can_receive():
                break
        else:
            if not self._values:
                raise ConfigException('No devices have been configured using config.devices.add(...).')
            else:
                raise ConfigException('At least one device must be a receiving device. All configured devices are not.')


class _ConfigDbs(object):
    __read_only_databases = None
    __writable_db = None
    
    def __init__(self, config, reactor, log):
        self._config = config
        self.__reactor = reactor
        self.__log = log
        
        self.__read_only_databases, diagnostics = databases_from_directory(
            self.__reactor,
            sibpath(__file__, '../data/dbs/'))
        if len(diagnostics) > 0:
            raise ConfigException(diagnostics)
    
    def add_directory(self, path):
        self._config._not_finished()
        path = str(path)
        dbs, path_diagnostics = databases_from_directory(self.__reactor, path)
        self.__read_only_databases.update(dbs)
        self.__report(path_diagnostics)
    
    def add_writable_database(self, path):
        self._config._not_finished()
        path = str(path)
        if self.__writable_db is not None:
            raise ConfigException('Multiple writable databases are not yet supported.')
        self.__writable_db, diagnostics = database_from_csv(self.__reactor, path, writable=True)
        self.__report((path, d) for d in diagnostics)
    
    def __report(self, path_diagnostics):
        for path, db_diagnostic in path_diagnostics:
            self.__log.warn('{path}: {db_diagnostic}', path=path, db_diagnostic=db_diagnostic)

    def _get_writable_database(self):
        if self.__writable_db is None:
            # TODO temporary stub till the client takes more configurability -- we should omit the writable db rather than having an unbacked one
            self.__writable_db = DatabaseModel(None, {}, writable=True)
        return self.__writable_db
    
    def _get_read_only_databases(self):
        if self.__read_only_databases is None:
            self.__read_only_databases = {}
        return self.__read_only_databases
    
    def _validate(self):
        """Check that the configuration is consistent and raise ConfigException if not."""


class _ConfigFeatures(object):
    def __init__(self, config):
        self._state = {
            'reboot': False,
            'stereo': True,
            '_test_disabled_feature': False,
            '_test_enabled_feature': True,
        }
        self.__config = config
    
    def enable(self, name):
        self.__config._not_finished()
        self._state[self.__validate(name)] = True
    
    def disable(self, name):
        self.__config._not_finished()
        self._state[self.__validate(name)] = False
    
    def __validate(self, name):
        name = six.text_type(name)
        if name not in self._state:
            raise ConfigException(u'Unknown feature name: %s' % name)
        return name
    
    def _get(self, name):
        return self._state[name]
    
    def _get_all(self):
        return dict(self._state)
    
    def _validate(self):
        """Check that the configuration is consistent and raise ConfigException if not."""
        pass


def execute_config(config_obj, config_file_or_directory):
    """Execute a config file or directory with the special environment.
    
    If a directory, sets the directory-based defaults.
    
    Note: does not _wait_and_validate()
    """
    if os.path.isdir(config_file_or_directory):
        _execute_config_file(config_obj, os.path.join(config_file_or_directory, 'config.py'))
        
        if not config_obj._state_filename:
            config_obj.persist_to_file(os.path.join(config_file_or_directory, 'state.json'))
        dbs_dir = os.path.join(config_file_or_directory, 'dbs-read-only')
        if os.path.isdir(dbs_dir):
            config_obj.databases.add_directory(dbs_dir)
    else:
        _execute_config_file(config_obj, config_file_or_directory)


__all__.append('execute_config')


def _execute_config_file(config_obj, path):
    # TODO: it was suggested that "runpy" is a better way to implement this; try it
    env = dict(builtins.__dict__)
    env.update({'config': config_obj})
    with open(path) as f:
        # going through compile() provides position information for tracebacks
        code = compile(f.read(), path, 'exec')
        six.exec_(code, env)


def print_config_exception(exc_info, destination):
    """Strip implementation code from an execute_config traceback and print it."""
    etype, value, tb = exc_info
    tb_list = traceback.extract_tb(tb)

    filtered_tb_list = []
    state = 'initial'
    for entry in tb_list:
        filename, line, function, _source_text = entry
        if state == 'initial':
            if function == '_execute_config_file':
                state = 'hide_execute'
        elif state == 'hide_execute':
            if not function == 'exec_' and not filename == '<string>':
                state = 'copy'
                filtered_tb_list.append(entry)
        elif state == 'copy':
            if filename == '<string>':  # skip six.exec_ wrapper
                continue
            if __file__.rstrip('c').endswith(filename):
                break
            else:
                filtered_tb_list.append(entry)
        else:
            raise Exception('broken state machine in print_config_exception')
    
    if not filtered_tb_list:
        print('[unfiltered]')
        # fall back to unfiltered
        filtered_tb_list = tb_list
    
    print('An error occurred while executing the ShinySDR configuration file:', file=destination)
    for line in traceback.format_list(filtered_tb_list):
        destination.write(line)
    for line in traceback.format_exception_only(etype, value):
        destination.write(line)


__all__.append('print_config_exception')


def write_default_config(new_config_path):
    # TODO: support enumerating osmosdr devices and configuring specifically for them
    # TODO: support more than one audio device (moot currently because gnuradio doesn't have a enumeration operation)
    from shinysdr.devices import find_audio_rx_names
    audio_rx_names = find_audio_rx_names()
    if audio_rx_names:
        has_audio = True
        audio_rx_name = audio_rx_names[0]
    else:
        has_audio = False
        audio_rx_name = ''
    try:
        importlib.import_module('shinysdr.plugins.osmosdr')
        has_osmosdr = True
    except ImportError:
        has_osmosdr = False
    
    config_text = '''\
# -*- coding: utf-8 -*-

# This is a ShinySDR configuration file. For more information about what can
# be put here, read the manual section on it, available from the running
# ShinySDR server at: http://localhost:8100/manual/configuration

from shinysdr.devices import AudioDevice
%(osmosdr_comment)sfrom shinysdr.plugins.osmosdr import OsmoSDRDevice
from shinysdr.plugins.simulate import SimulatedDevice

# OsmoSDR generic driver; handles USRP, RTL-SDR, FunCube Dongle, HackRF, etc.
# To select a specific device, replace '' with 'rtl=0' etc.
%(osmosdr_comment)sconfig.devices.add(u'osmo', OsmoSDRDevice(''))

# For hardware which uses a sound-card as its ADC or appears as an
# audio device.
%(audio_comment)sconfig.devices.add(u'audio', AudioDevice(rx_device='%(audio_rx_name)s'))

# Locally generated RF signals for test purposes.
config.devices.add(u'sim', SimulatedDevice())

config.serve_web(
    # These are in Twisted endpoint description syntax:
    # <http://twistedmatrix.com/documents/current/api/twisted.internet.endpoints.html#serverFromString>
    # Note: ws_endpoint must currently be 1 greater than http_endpoint; if one
    # is SSL then both must be. These restrictions will be relaxed later.
    http_endpoint='tcp:8100',
    ws_endpoint='tcp:8101',

    # A secret placed in the URL as simple access control. Does not
    # provide any real security unless using HTTPS. The default value
    # in this file has been automatically generated from 128 random bits.
    # Set to None to not use any secret.
    root_cap='%(root_cap)s',
    
    # Page title / station name
    title='ShinySDR')
''' % {
        'root_cap': generate_cap(),
        'audio_comment': '' if has_audio else '# ',
        'audio_rx_name': audio_rx_name,
        'osmosdr_comment': '' if has_osmosdr else '# ',
    }
    
    os.mkdir(new_config_path)
    with open(os.path.join(new_config_path, 'config.py'), 'wb') as f:
        f.write(config_text.encode('utf-8'))
    os.mkdir(os.path.join(new_config_path, 'dbs-read-only'))


__all__.append('write_default_config')


class ConfigException(Exception):
    """Indicates erroneous configuration of some type."""


__all__.append('ConfigException')


class ConfigTooLateException(ConfigException):
    """Indicates that a config method was called too late for it to take effect."""
    
    def __init__(self):
        super(ConfigTooLateException, self).__init__('Too late to modify configuration')


__all__.append('ConfigTooLateException')
