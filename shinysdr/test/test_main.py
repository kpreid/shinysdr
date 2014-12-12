# Copyright 2013, 2014 Kevin Reid <kpreid@switchb.org>
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
See also test_config.py.
'''


from __future__ import absolute_import, division

import os
import os.path
import shutil
import tempfile
import textwrap

from twisted.internet import defer
from twisted.trial import unittest

from shinysdr import main


class TestMain(unittest.TestCase):
    def setUp(self):
        self.__temp_dir = tempfile.mkdtemp(prefix='shinysdr_test_main_tmp')
        state_name = os.path.join(self.__temp_dir, 'state')
        self.__config_name = os.path.join(self.__temp_dir, 'config')
        with open(self.__config_name, 'w') as config:
            config.write(textwrap.dedent('''\
                import shinysdr.plugins.simulate
                config.devices.add('sim_foobar', shinysdr.plugins.simulate.SimulatedDevice())
                config.persist_to_file(%r)
                config.serve_web(
                    http_endpoint='tcp:0',
                    ws_endpoint='tcp:0',
                    root_cap=None)
            ''') % (state_name,))
    
    def tearDown(self):
        shutil.rmtree(self.__temp_dir)
    
    def __run_main(self):
        return main.main(
            argv=['shinysdr', self.__config_name],
            _abort_for_test=True)
    
    @defer.inlineCallbacks
    def test_main_first_run_sources(self):
        '''Regression: first run with no state file would fail due to assumptions about the source names.'''
        yield main.main(
            argv=['shinysdr', self.__config_name],
            _abort_for_test=True)
    
    @defer.inlineCallbacks
    def test_persistence(self):
        '''Test that state persists.'''
        (top, note_dirty) = yield self.__run_main()
        self.assertEqual(top.get_unpaused(), True)  # check initial assumption
        top.set_unpaused(False)
        note_dirty()
        (top, note_dirty) = yield self.__run_main()
        self.assertEqual(top.get_unpaused(), False)  # check persistence

    @defer.inlineCallbacks
    def test_minimal(self):
        '''Test that things function with no state file and no servers.'''
        with open(self.__config_name, 'w') as config:
            config.write(textwrap.dedent('''\
                import shinysdr.plugins.simulate
                config.devices.add('sim_foobar', shinysdr.plugins.simulate.SimulatedDevice())
            '''))
        
        (top, note_dirty) = yield self.__run_main()
        self.assertEqual(top.get_unpaused(), True)  # check initial assumption
        top.set_unpaused(False)
        note_dirty()
        (top, note_dirty) = yield self.__run_main()
        self.assertEqual(top.get_unpaused(), True)  # expect NO persistence
    
    @defer.inlineCallbacks
    def test_deferred_config(self):
        '''Test that the config can defer.'''
        with open(self.__config_name, 'w') as config:
            config.write(textwrap.dedent('''\
                import shinysdr.plugins.simulate
                from twisted.internet import reactor
                from twisted.internet.task import deferLater
                d = deferLater(reactor, 0.001, lambda: config.devices.add('a_source', shinysdr.plugins.simulate.SimulatedDevice()))
                config.wait_for(d)
            '''))
        
        (top, _note_dirty) = yield self.__run_main()
        self.assertEqual(top.state()['sources'].get().state().keys(), ['a_source'])
