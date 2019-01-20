# Copyright 2013, 2014, 2015, 2016 Kevin Reid and the ShinySDR contributors
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
See also test_config.py.
"""


from __future__ import absolute_import, division, print_function, unicode_literals

import os
import os.path
import textwrap

from twisted.internet import defer
from twisted.internet import reactor as the_reactor
from twisted.internet.task import deferLater
from twisted.trial import unittest

from shinysdr import main
from shinysdr.i.persistence import _PERSISTENCE_DELAY
from shinysdr.testutil import Files


class TestMain(unittest.TestCase):
    def setUp(self):
        self.__files = Files({})
        # TODO: use config dir instead of deprecated config file
        state_name = os.path.join(self.__files.dir, 'state')
        self.__config_name = os.path.join(self.__files.dir, 'config')
        with open(self.__config_name, 'w') as config:
            config.write(textwrap.dedent('''\
                import shinysdr.plugins.simulate
                config.devices.add('sim_foo', shinysdr.plugins.simulate.SimulatedDeviceForTest())
                config.devices.add('sim_bar', shinysdr.plugins.simulate.SimulatedDeviceForTest())
                config.persist_to_file(%r)
                config.serve_web(
                    http_endpoint='tcp:0',
                    ws_endpoint='tcp:0',
                    root_cap=None)
            ''') % (state_name,))
    
    def tearDown(self):
        self.__files.close()
    
    def __run_main(self):
        return main.main(
            argv=['shinysdr', self.__config_name],
            _abort_for_test=True)
    
    @defer.inlineCallbacks
    def test_main_first_run_sources(self):
        """Regression: first run with no state file would fail due to assumptions about the source names."""
        yield main.main(
            argv=['shinysdr', self.__config_name],
            _abort_for_test=True)
    
    @defer.inlineCallbacks
    def test_persistence(self):
        """Test that state persists."""
        app = yield self.__run_main()
        rxf = app.get_receive_flowgraph()
        self.assertEqual(rxf.get_source_name(), 'sim_bar')  # check initial assumption
        rxf.set_source_name('sim_foo')
        # TODO: use Clock so we don't have to make a real delay
        yield deferLater(the_reactor, _PERSISTENCE_DELAY + 0.01, lambda: None)
        app = yield self.__run_main()
        rxf = app.get_receive_flowgraph()
        self.assertEqual(rxf.get_source_name(), 'sim_foo')  # check persistence

    @defer.inlineCallbacks
    def test_minimal(self):
        """Test that things function with no state file and no servers."""
        with open(self.__config_name, 'w') as config:
            config.write(textwrap.dedent('''\
                import shinysdr.plugins.simulate
                config.devices.add('sim_foo', shinysdr.plugins.simulate.SimulatedDeviceForTest())
                config.devices.add('sim_bar', shinysdr.plugins.simulate.SimulatedDeviceForTest())
            '''))
        
        app = yield self.__run_main()
        rxf = app.get_receive_flowgraph()
        self.assertEqual(rxf.get_source_name(), 'sim_bar')  # check initial assumption
        rxf.set_source_name('sim_foo')
        yield deferLater(the_reactor, _PERSISTENCE_DELAY + 0.01, lambda: None)
        app = yield self.__run_main()
        rxf = app.get_receive_flowgraph()
        self.assertEqual(rxf.get_source_name(), 'sim_bar')  # expect NO persistence
    
    @defer.inlineCallbacks
    def test_deferred_config(self):
        """Test that the config can defer."""
        with open(self.__config_name, 'w') as config:
            config.write(textwrap.dedent('''\
                import shinysdr.plugins.simulate
                from twisted.internet import reactor
                from twisted.internet.task import deferLater
                d = deferLater(reactor, 0.001, lambda: config.devices.add('a_source', shinysdr.plugins.simulate.SimulatedDeviceForTest()))
                config.wait_for(d)
            '''))
        
        app = yield self.__run_main()
        self.assertEqual(set(app.get_receive_flowgraph().state()['sources'].get().state().keys()), {'a_source'})
