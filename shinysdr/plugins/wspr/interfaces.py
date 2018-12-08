# Copyright 2017 Kevin Reid and the ShinySDR contributors
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

from zope.interface import Interface


class IWAVIntervalListener(Interface):
    def fileClosed(filename):
        """A recording just finished and the file is closed."""

    def fileOpened(filename):
        """A file was just opened and recording has started."""

    def filename(start_time):
        """Return what the recording should be named.

        `start_time` is in seconds since epoch.
        """
