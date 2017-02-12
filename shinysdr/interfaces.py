# Copyright 2013, 2014, 2015, 2016 Kevin Reid <kpreid@switchb.org>
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

"""API for plugins, and related things.

This module contains objects and interfaces used by plugins to declare
the functionality they provide.
"""

from __future__ import absolute_import, division

from twisted.plugin import IPlugin
from zope.interface import Interface, implements

from shinysdr.i.modes import IModeDef
from shinysdr.i.network.app import IClientResourceDef
from shinysdr.types import EnumRow

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
    
    def get_band_filter_shape():
        """
        Returns a dict describing the shape of the demodulator's input filter.
        
        This is used to display the filter on-screen and to determine when to disable a receiver because the demodulator's passband is outside the device's bandwidth.
        
        The dict must have the following elements:
            'low': lower edge (Hz relative to nominal carrier frequency, usually negative)
            'high': upper edge (Hz relative to nominal carrier frequency, usually positive)
            'width': transition band width
        """
    
    def get_output_type():
        """
        Return the SignalType of the demodulator's output.
        
        The output must be stereo audio, mono audio, or nothing. Note that stereo audio is represented as a vector of two floats, not as two output ports.
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


__all__.append('IModulator')


class ITunableDemodulator(IDemodulator):
    def set_rec_freq(freq):
        """
        Set the nominal (carrier) frequency offset of the signal to be demodulated within the input signal.
        """


__all__.append('ITunableDemodulator')


class IHasFrequency(Interface):
    # TODO: document this
    def get_freq():
        pass


__all__.append('IHasFrequency')


class ModeDef(object):
    implements(IPlugin, IModeDef)
    
    # Twisted plugin system caches whether-a-plugin-class-was-found permanently, so we need to avoid _not_ having a ModeDef if the plugin has some sort of dependency it checks -- thus the 'available' flag can be used to hide a mode while still having an _IModeDef
    def __init__(self,
            mode,
            info,
            demod_class,
            mod_class=None,
            available=True):
        """
        mode: String uniquely identifying this mode, typically a standard abbreviation written in uppercase letters (e.g. "USB", "WFM").
        info: An EnumRow object with a label for the mode, or a string.
            The EnumRow sort key should be like the mode value but organized for sorting with space as a separator of qualifiers (e.g. "SSB U", "FM W").
        demod_class: Class to instantiate to create a demodulator for this mode.
        mod_class: Class to instantiate to create a modulator for this mode.
        (TODO: cite demodulator and modulator interface docs)
        available: If false, this mode definition will be ignored.
        """
        self.mode = unicode(mode)
        self.info = EnumRow(info)
        self.demod_class = demod_class
        self.mod_class = mod_class
        self.available = bool(available)


__all__.append('ModeDef')


class ClientResourceDef(object):
    implements(IPlugin, IClientResourceDef)
    
    def __init__(self, key, resource, load_css_path=None, load_js_path=None):
        self.key = key
        self.resource = resource
        self.load_css_path = load_css_path
        self.load_js_path = load_js_path


__all__.append('ClientResourceDef')
