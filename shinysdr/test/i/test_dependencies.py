# Copyright 2015, 2016 Kevin Reid <kpreid@switchb.org>
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

import os.path

import six

from twisted.trial import unittest

from shinysdr.i.dependencies import DependencyTester


class TestDependencyTester(unittest.TestCase):
    def setUp(self):
        self.t = DependencyTester()
    
    def test_module_ok(self):
        self.t.check_module('shinysdr.test.i.test_dependencies', '<dep name>')
        self.assertEqual(self.t.report(), None)
    
    def test_module_missing(self):
        self.t.check_module('shinysdr.nonexistent_module_name', '<dep name>')
        self.assertEqual(self.t.report(),
            'The following libraries/programs are missing:\n\t<dep name>  (Check: shinysdr.nonexistent_module_name not present.)\nPlease (re)install current versions.')
    
    def test_module_broken_import(self):
        self.t.check_module('shinysdr.test.i.broken_deps.imports', '<dep name>')
        if six.PY2:
            self.assertEqual(self.t.report(),
                'The following libraries/programs are not installed correctly:\n\t<dep name>  (Check: shinysdr.test.i.broken_deps.imports failed to import (No module named nonexistent_module_in_dep).)\nPlease (re)install current versions.')
        else:
            self.assertEqual(self.t.report(),
                'The following libraries/programs are not installed correctly:\n\t<dep name>  (Check: shinysdr.test.i.broken_deps.imports failed to import (No module named \'shinysdr.test.nonexistent_module_in_dep\').)\nPlease (re)install current versions.')
    
    def test_module_broken_other(self):
        self.t.check_module('shinysdr.test.i.broken_deps.misc', '<dep name>')
        self.assertEqual(self.t.report(),
            'The following libraries/programs are not installed correctly:\n\t<dep name>  (Check: shinysdr.test.i.broken_deps.misc failed to import (boo).)\nPlease (re)install current versions.')
    
    def test_attr_ok(self):
        self.t.check_module_attr('shinysdr.test.i.test_dependencies', '<dep name>', 'TestDependencyTester')
        self.assertEqual(self.t.report(), None)
    
    def test_attr_path_ok(self):
        self.t.check_module_attr('shinysdr.test.i.test_dependencies', '<dep name>', 'TestDependencyTester.test_attr_path_ok')
        self.assertEqual(self.t.report(), None)
    
    def test_attr_missing(self):
        self.t.check_module_attr('shinysdr.test.i.test_dependencies', '<dep name>', 'nonexistent_attr')
        self.assertEqual(self.t.report(),
            'The following libraries/programs are too old:\n\t<dep name>  (Check: shinysdr.test.i.test_dependencies.nonexistent_attr not present.)\nPlease (re)install current versions.')
    
    # note: 'broken attr' (hasattr true but it raises on get) is theoretically possible but hard to cause
    
    def test_file_ok(self):
        self.t.check_jsdep_file(__file__, 'broken_deps/__init__.py', '<dep name>')
        self.assertEqual(self.t.report(), None)
    
    def test_file_missing(self):
        self.t.check_jsdep_file(__file__, 'broken_deps/nonexistent_filename', '<dep name>')
        self.assertEqual(self.t.report(),
            'The following files are missing:\n\t<dep name>  (Check: ' + os.path.dirname(__file__) + '/broken_deps/nonexistent_filename does not exist.)\nPlease (re)run fetch-js-deps.sh and, if applicable, setup.py install.')
