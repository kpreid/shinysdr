# Copyright 2013 Kevin Reid <kpreid@switchb.org>
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

from __future__ import absolute_import, division

import os
import os.path
import shutil
import tempfile
import textwrap

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
				sources = {
					'sim_foobar': shinysdr.plugins.simulate.SimulatedSource(),
				}
				stateFile = %r
				databasesDir = 'NONEXISTENT'
				httpPort = 'tcp:0'
				wsPort = 'tcp:0'
				rootCap = None
			''') % (state_name,))
	
	def tearDown(self):
		shutil.rmtree(self.__temp_dir)
	
	def test_main_first_run_sources(self):
		'''Regression: first run with no state file would fail due to assumptions about the source names.'''
		main.main(
			args_strings=[self.__config_name],
			_abort_for_test=True)
