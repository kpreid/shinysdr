# -*- coding: utf-8 -*-
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

"""Test objects used by client-server integration and equivalence tests."""

from __future__ import absolute_import, division, print_function, unicode_literals

from shinysdr.types import BulkDataElement, BulkDataT, EnumRow, RangeT, ReferenceT, to_value_type
from shinysdr.values import CellDict, CollectionState, ElementSinkCell, ExportedState, LooseCell, PollingCell, StringSinkCell, ViewCell, command, exported_value, nullExportedState, setter, unserialize_exported_state


SHARED_TEST_OBJECTS_CAP = 'shared_test_objects'


class SharedTestObjects(ExportedState):
    @exported_value(type=unicode, changes='never')
    def get_smoke_test(self):
        return 'SharedTestObjects exists'
