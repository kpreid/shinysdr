# Copyright 2018 Kevin Reid and the ShinySDR contributors
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

import re

import six


def bytes_or_ascii(value):
    """Emulate Python 2 behavior of automatic string encoding or pass-through."""
    if isinstance(value, bytes):
        return value
    else:
        return six.text_type(value).encode('ascii')


def defaultstr(value):
    """Equivalent to str(); used to explicitly indicate situations where what we need is the default string type for the Python version.
    
    The common such situations are:
    * GNU Radio block names
    * the built-in array module, which in Python 2.7.6 does not accept a unicode string.
    """
    return str(value)


def repr_no_string_tag(value):
    """As repr() but if the result would start with "b'" or "u'", remove the "b" or "u".
    
    This allows for consistent output between Python 2 and 3 but also may be used for user-facing strings where on Python 2 we don't particularly want to show a "u".
    """
    return re.sub("^[bu]'", "'", repr(value))
