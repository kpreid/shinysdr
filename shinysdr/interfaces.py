# -*- coding: utf-8 -*-
# Copyright 2013, 2014, 2015, 2016, 2017, 2018 Kevin Reid <kpreid@switchb.org>
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

# pylint: disable=signature-differs
# (pylint is confused by interfaces)

from __future__ import absolute_import, division, print_function, unicode_literals

from collections import namedtuple

from twisted.plugin import IPlugin
from zope.interface import Attribute, Interface, implementer

from shinysdr.i.modes import IModeDef
from shinysdr.types import EnumRow

__all__ = []  # appended later


class IDemodulatorFactory(Interface):
    def __call__(mode, input_rate, context):
        """
        Returns a new IDemodulator.
        
        mode: unicode, the mode to be demodulated (should be one the factory/class was declared to support)
        input_rate: float, sample rate the demodulator must accept
        context: an IDemodulatorContext
        
        May support additional keyword arguments as supplied by unserialize_exported_state.
        """


__all__.append('IDemodulatorFactory')


class IDemodulator(Interface):
    """
    Demodulators may also wish to implement:
    IDemodulatorModeChange
    ITunableDemodulator
    
    Additional constraints:
    
    The object must also be GNU Radio block with one gr_complex input, and output as described by get_output_type().
    """
    
    def get_band_shape():
        """
        Returns a BandShape object describing the portion of its input signal which the demodulator uses (typically, the shape of its filter).
        
        Should be exported, typically like:
            @exported_value(type=BandShape, changes='never')
        
        This is used to display the filter on-screen and to determine when the demodulator's input requirements are satisfied by the device's tuning.
        """
    
    def get_output_type():
        """
        Return the SignalType of the demodulator's output.
        
        The output must be stereo audio, mono audio, or nothing. Note that stereo audio is represented as a vector of two floats, not as two output ports.
        """


__all__.append('IDemodulator')


class IDemodulatorContext(Interface):
    def rebuild_me():
        """Request that this demodulator be discarded and an identically configured copy be created.
        
        This is needed when something such as the output type of the demodulator changes; it may also be used any time constructing a new demodulator is more convenient than changing the internal structure of an existing one.
        """

    def lock():
        """
        Use this method instead of gr.hier_block2.lock().
        
        This differs in that it will avoid acquiring the lock if it is already held (implementing a "recursive lock"). It is therefore suitable for use when the demodulator is being invoked in a situation where the lock may already be held.
        """

    def unlock():
        """Use in pairs with IDemodulatorContext.lock()."""
    
    def output_message(message):
        """Report a message output from the demodulator, such as in demodulators which handle packets rather than audio.
        
        The message object should provide shinysdr.telemetry.ITelemetryMessage.
        """
    
    def get_absolute_frequency_cell():
        """Returns a cell containing the original RF carrier frequency of the signal to be demodulated — the frequency the signal entering the demodulator has been shifted down from."""


class ITunableDemodulator(IDemodulator):
    """If a demodulator implements this interface, then there may be a arbitrary frequency offset in its input signal, which it will be informed of via the set_rec_freq method."""
    
    def set_rec_freq(freq):
        """
        Set the nominal (carrier) frequency offset of the signal to be demodulated within the input signal.
        """


__all__.append('ITunableDemodulator')


class IDemodulatorModeChange(IDemodulator):
    """If a demodulator implements this interface, then it may be asked to reconfigure itself to demodulate a different mode."""
    
    def can_set_mode(mode):
        """
        Return whether this demodulator can reconfigure itself to demodulate the specified mode.
        
        If it returns False, it will typically be replaced with a newly created demodulator.
        """
    
    def set_mode(mode):
        """
        Per can_set_mode.
        """


__all__.append('IDemodulatorModeChange')


# TODO: BandShape doesn't really belong here but it is related to IDemodulator. Find better location.

# All frequencies are relative to the demodulator's input signal (i.e. baseband)
_BandShape = namedtuple('BandShape', [
    'stop_low',  # float; lower edge of stopband
    'pass_low',  # float; lower edge of passband
    'pass_high',  # float; upper edge of passband
    'stop_high',  # float; upper edge of stopband
    'markers',  # dict of float to string; labels of significant frequencies (e.g. FSK mark and space)
])


class BandShape(_BandShape):
    @classmethod
    def lowpass_transition(cls, cutoff, transition, markers=None):
        if markers is None:
            markers = {}
        h = transition / 2.0
        return cls(
            stop_low=-cutoff - h,
            pass_low=-cutoff + h,
            pass_high=cutoff - h,
            stop_high=cutoff + h,
            markers=markers)

    @classmethod
    def bandpass_transition(cls, transition, low, high, markers=None):
        if markers is None:
            markers = {}
        h = transition / 2.0
        return cls(
            stop_low=low - h,
            pass_low=low + h,
            pass_high=high - h,
            stop_high=high + h,
            markers=markers)


__all__.append('BandShape')


class IModulatorFactory(Interface):
    def __call__(mode, context):
        """
        Returns a new IModulator.
        
        mode: unicode, the mode to be modulated (should be one the factory/class was declared to support)
        context: always None, will later become IModulatorContext when that exists.
        
        May support additional keyword arguments as supplied by unserialize_exported_state.
        """


class IModulator(Interface):
    """
    Additional constraints:
    
    The object must also be a GNU Radio block with one gr_complex output, and input as described by get_input_type().
    """
    
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


class IHasFrequency(Interface):
    # TODO: document this
    def get_freq():
        pass


__all__.append('IHasFrequency')


@implementer(IPlugin, IModeDef)
class ModeDef(object):
    # Twisted plugin system caches whether-a-plugin-class-was-found permanently, so we need to avoid _not_ having a ModeDef if the plugin has some sort of dependency it checks -- thus the 'available' flag can be used to hide a mode while still having an _IModeDef
    def __init__(self,
            mode,
            info,
            demod_class,
            mod_class=None,
            unavailability=None):
        """
        mode: String uniquely identifying this mode, typically a standard abbreviation written in uppercase letters (e.g. "USB", "WFM").
        info: An EnumRow object with a label for the mode, or a string.
            The EnumRow sort key should be like the mode value but organized for sorting with space as a separator of qualifiers (e.g. "SSB U", "FM W").
        demod_class: Class (or factory function) to instantiate to create a demodulator for this mode. Should provide IDemodulatorFactory but need not declare it.
        mod_class: Class (or factory function) to instantiate to create a modulator for this mode. Should provide IModulatorFactory but need not declare it.
        unavailability: This mode definition will be ignored if this is a string rather than None. The string should be an error message informative to the user (plain text, significant whitespace).
        """
        if isinstance(unavailability, bool):
            raise Exception('unavailability should be a string or None')
        
        self.mode = unicode(mode)
        self.info = EnumRow(info)
        self.demod_class = demod_class
        self.mod_class = mod_class
        self.unavailability = None if unavailability is None else unicode(unavailability)
        
    @property
    def available(self):
        return self.unavailability is None


__all__.append('ModeDef')


class _IClientResourceDef(Interface):
    """
    Client plugin interface object. 

    This interface is needed to make the plugin system work and is not intended to be reimplemented; just use ClientResourceDef.
    """
    
    key = Attribute("""A unique string, prefixed by the plugin's package name.""")
    resource = Attribute(
        """A twisted.web.resource.Resource to be added to the web server.
    
        Must not provide any authority (e.g. just static CSS/JS files are OK).
        """)
    load_css_path = Attribute("""Optional path relative to within `resource` to load as CSS.""")
    load_js_path = Attribute("""Optional path relative to within `resource` to load as JavaScript.""")


@implementer(IPlugin, _IClientResourceDef)
class ClientResourceDef(object):
    def __init__(self, key, resource, load_css_path=None, load_js_path=None):
        """
        key: A unique string, prefixed by the plugin's package name.
        resource: A twisted.web.resource.Resource to be added to the web server.
            Must not provide any authority (e.g. just static CSS/JS files are OK).
        load_css_path: Optional path relative to within `resource` to load as CSS.
        load_js_path: Optional path relative to within `resource` to load as JavaScript.
        """
        self.key = key
        self.resource = resource
        self.load_css_path = load_css_path
        self.load_js_path = load_js_path


__all__.append('ClientResourceDef')
