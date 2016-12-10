# Copyright 2014, 2015, 2016 Kevin Reid <kpreid@switchb.org>
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

from twisted.trial import unittest

from shinysdr.i.persistence import PersistenceChangeDetector
from shinysdr.test.testutil import SubscriptionTester
from shinysdr.values import ExportedState, Reference, exported_value, nullExportedState, setter


class TestPersistenceChangeDetector(unittest.TestCase):
    def setUp(self):
        self.st = SubscriptionTester()
        self.o = ValueAndBlockSpecimen(ValueAndBlockSpecimen(ExportedState()))
        self.calls = 0
        self.d = PersistenceChangeDetector(self.o, self.__callback, subscription_context=self.st.context)
    
    def __callback(self):
        self.calls += 1
    
    def test_1(self):
        self.assertEqual(self.d.get(), {
            u'value': 0,
            u'block': {
                u'value': 0,
                u'block': {},
            },
        })
        self.assertEqual(0, self.calls)
        self.o.set_value(1)
        self.assertEqual(0, self.calls)
        self.st.advance()
        self.assertEqual(1, self.calls)
        self.o.set_value(2)
        self.st.advance()
        self.assertEqual(1, self.calls) # only fires once
        self.assertEqual(self.d.get(), {
            u'value': 2,
            u'block': {
                u'value': 0,
                u'block': {},
            },
        })
        self.st.advance()
        self.assertEqual(1, self.calls)
        self.o.get_block().set_value(3)  # pylint: disable=no-member
        self.st.advance()
        self.assertEqual(2, self.calls)
        self.assertEqual(self.d.get(), {
            u'value': 2,
            u'block': {
                u'value': 3,
                u'block': {},
            },
        })


class ValueAndBlockSpecimen(ExportedState):
    def __init__(self, block=nullExportedState, value=0):
        self.__value = value
        self.__block = block
    
    @exported_value(type=Reference(), changes='never')
    def get_block(self):
        return self.__block
    
    @exported_value(type=float, parameter='value', changes='this_setter')
    def get_value(self):
        return self.__value
    
    @setter
    def set_value(self, value):
        self.__value = value
