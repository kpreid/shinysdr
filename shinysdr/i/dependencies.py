#!/usr/bin/env python

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

from importlib import import_module
import os.path

import six

from twisted.python.util import sibpath


class DependencyTester(object):
    """
    Attempt to import things and collect reports of failure.
    """
    def __init__(self):
        self.__missing = set()
        self.__broken = set()
        self.__old = set()
        self.__missing_files = set()

    def check_module_attr(self, module_name, dep_name, attr_path, old=False):
        module = self.check_module(module_name, dep_name, old=old)
        self.check_attr(module_name, dep_name, module, attr_path, old=True)
    
    def check_attr(self, module_name, dep_name, module, attr_path, old=False):
        if not hasattr_path(module, attr_path):
            entry = (dep_name, '%s.%s not present.' % (module_name, attr_path))
            if old:
                self.__old.add(entry)
            else:
                self.__missing.add(entry)
            return
        # pylint: disable=broad-except
        try:
            getattr_path(module, attr_path)
        except Exception:
            self.__broken.add((dep_name, 'Error checking for %s.%s.' % (module_name, attr_path)))  # TODO mention error
    
    def check_module(self, module_name, dep_name, old=False):
        # pylint: disable=broad-except
        try:
            return import_module(module_name)
        except ImportError as e:
            if import_error_matches(e, module_name):
                self.__missing.add((dep_name, '%s not present.' % module_name))
            else:
                # actually a loading error
                self.__broken.add((dep_name, '%s failed to import (%s).' % (module_name, e)))
        except Exception as e:
            self.__broken.add((dep_name, '%s failed to import (%s).' % (module_name, e)))
            return None
    
    # This method has an overly-specific name because it has an overly-specific report message.
    def check_jsdep_file(self, relative_to_pathname, expected_pathname, dep_name):
        absolute_path = sibpath(relative_to_pathname, expected_pathname)
        if not os.path.exists(absolute_path):
            self.__missing_files.add((dep_name, '%s does not exist.' % absolute_path))
    
    def report(self):
        report_text = ''
        if len(self.__missing) > 0:
            report_text += 'The following libraries/programs are missing:\n' + self.__format_entries(self.__missing)
        if len(self.__broken) > 0:
            report_text += 'The following libraries/programs are not installed correctly:\n' + self.__format_entries(self.__broken)
        if len(self.__old) > 0:
            report_text += 'The following libraries/programs are too old:\n' + self.__format_entries(self.__old)
        if report_text != '':
            report_text += 'Please (re)install current versions.'
        if len(self.__missing_files) > 0:
            if report_text != '':
                report_text += '\n'
            report_text += 'The following files are missing:\n' + self.__format_entries(self.__missing_files)
            report_text += 'Please (re)run fetch-js-deps.sh and, if applicable, setup.py install.'
        if report_text != '':
            return report_text
        else:
            return None
    
    def __format_entries(self, entries):
        out = ''
        for entry in entries:
            item, check = entry
            out += '\t%s  (Check: %s)\n' % (item, check)
        return out


def import_error_matches(import_error, module_name):
    if six.PY2:
        msg = six.text_type(import_error)
        # indirect because the message includes only the last name component
        prefix = 'No module named '
        return msg.startswith(prefix) and module_name.endswith(msg[len(prefix):])
    else:
        return module_name == import_error.name


def hasattr_path(specimen, path):
    splat = path.split('.', 1)
    if len(splat) == 1:
        return hasattr(specimen, path)
    else:
        first, rest = splat
        return hasattr(specimen, first) and hasattr_path(getattr(specimen, first), rest)


def getattr_path(specimen, path):
    splat = path.split('.', 1)
    if len(splat) == 1:
        return getattr(specimen, path)
    else:
        first, rest = splat
        return getattr_path(getattr(specimen, first), rest)
