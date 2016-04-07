# Copyright 2013, 2014, 2015 Kevin Reid <kpreid@switchb.org>
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

# pylint: disable=no-init
# (pylint is confused by interfaces)

from __future__ import absolute_import, division

from twisted.plugin import IPlugin, getPlugins
from zope.interface import Interface, implements  # available via Twisted

from shinysdr import plugins


__all__ = []  # appended later


class IDemodulator(Interface):
    def can_set_mode(mode):
        """
        Return whether this demodulator can reconfigure itself to demodulate the specified mode.
        
        If it returns False, it will typically be replaced with a newly created demodulator.
        """
    
    def set_mode(mode):
        """
        Per can_set_mode.
        """
    
    def get_half_bandwidth():
        """
        TODO explain
        """
    
    def get_output_type():
        """
        Return the SignalType of the demodulator's output.
        
        The output must be stereo audio, mono audio, or nothing.
        """


__all__.append('IDemodulator')


class IModulator(Interface):
    def can_set_mode(mode):
        """
        Return whether this modulator can reconfigure itself to modulate the specified mode.
        
        If it returns False, it will typically be replaced with a newly created modulator.
        """
    
    def set_mode(mode):
        """
        Per can_set_mode.
        """
    
    def get_input_type():
        """
        Return the SignalType of the modulator's required input, which must currently be mono audio at any sample rate.
        """
    
    def get_output_type():
        """
        Return the SignalType of the modulator's output, which must currently be IQ at any sample rate.
        """


class ITunableDemodulator(IDemodulator):
    def set_rec_freq(freq):
        """
        Set the nominal (carrier) frequency offset of the signal to be demodulated within the input signal.
        """


__all__.append('ITunableDemodulator')


class _IModeDef(Interface):
    """
    Demodulator plugin interface object
    """
    # Only needed to make the plugin system work
    # TODO write interface methods anyway


class ModeDef(object):
    implements(IPlugin, _IModeDef)
    
    # Twisted plugin system caches whether-a-plugin-class-was-found permanently, so we need to avoid _not_ having a ModeDef if the plugin has some sort of dependency it checks -- thus the 'available' flag can be used to hide a mode while still having an _IModeDef
    def __init__(self,
            mode,
            label,
            demod_class,
            mod_class=None,
            available=True):
        """
        mode: String uniquely identifying this mode, typically a standard abbreviation written in uppercase letters (e.g. "USB").
        label: String displayed to the user to identify this mode (e.g. "Broadcast FM").
        demod_class: Class to instantiate to create a demodulator for this mode.
        mod_class: Class to instantiate to create a modulator for this mode.
        (TODO: cite demodulator and modulator interface docs)
        available: If false, this mode definition will be ignored.
        """
        self.mode = mode
        self.label = label
        self.demod_class = demod_class
        self.mod_class = mod_class
        self.available = available


__all__.append('ModeDef')


# Object for memoizing results of getPlugins(_IModeDef)
class _ModeTable(object):
    def __init__(self):
        self.__modes = {p.mode: p for p in getPlugins(_IModeDef, plugins) if p.available}
    
    def get_modes(self):
        return self.__modes.values()
    
    def lookup_mode(self, mode):
        return self.__modes.get(mode)


_mode_table = None


def _get_mode_table():
    global _mode_table
    if _mode_table is None:
        _mode_table = _ModeTable()
    return _mode_table


def get_modes():
    return _get_mode_table().get_modes()


__all__.append('get_modes')


def lookup_mode(mode):
    return _get_mode_table().lookup_mode(mode)


__all__.append('lookup_mode')
