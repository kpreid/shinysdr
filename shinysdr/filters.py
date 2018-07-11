# Copyright 2015, 2016, 2017 Kevin Reid <kpreid@switchb.org>
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

"""
GNU Radio blocks which automatically compute appropriate filter designs.
"""

from __future__ import absolute_import, division, print_function, unicode_literals

from fractions import gcd
from math import pi, sin, cos

import six

from gnuradio import gr
from gnuradio.fft import window
from gnuradio import filter as grfilter  # don't shadow builtin
from gnuradio.filter import pfb
from gnuradio.filter import firdes
from gnuradio.filter import rational_resampler

from shinysdr.interfaces import BandShape
from shinysdr.i.math import factorize, small_factor_at_least


__all__ = []  # appended later

# Use rational_resampler_ccf rather than arb_resampler_ccf. This is less efficient, but avoids the bug <http://gnuradio.org/redmine/issues/713> where the latter block will hang the flowgraph if it is reused. When that is fixed, turn this flag off and maybe ditch the code for it.
_use_rational_resampler = True


class _MultistageChannelFilterPlan(object):
    """
    Description of a MultistageChannelFilter without any instantiation. The analogue of
    an array of taps for a single-stage filter.
    """
    
    def __init__(self, stage_designs, freq_xlate_stage, cutoff_freq, transition_width, taps=None):
        self.__stage_designs = stage_designs
        self.__taps = taps if taps is not None else [None for _ in stage_designs]
        self.__freq_xlate_stage = freq_xlate_stage
        self.__cutoff_freq = float(cutoff_freq)
        self.__transition_width = float(transition_width)
        self.__band_shape = BandShape.lowpass_transition(
            cutoff=self.__cutoff_freq,
            transition=self.__transition_width)
    
    def get_stage_designs(self):
        return self.__stage_designs
    
    def get_stage_designs_and_taps(self):
        return zip(self.__stage_designs, self.__taps)
    
    def get_freq_xlate_stage(self):
        return self.__freq_xlate_stage

    def get_cutoff_freq(self):
        return self.__cutoff_freq
    
    def get_transition_width(self):
        return self.__transition_width
    
    def get_shape(self):
        return self.__band_shape
    
    def replace(self, cutoff_freq=None, transition_width=None):
        if cutoff_freq is None:
            cutoff_freq = self.__cutoff_freq
        if transition_width is None:
            transition_width = self.__transition_width
        assert cutoff_freq > 0
        assert transition_width > 0
        return _MultistageChannelFilterPlan(
            stage_designs=self.__stage_designs,
            taps=[
                design.calculate_taps(
                    final_cutoff=cutoff_freq,
                    final_transition=transition_width)
                for design in self.__stage_designs],
            freq_xlate_stage=self.__freq_xlate_stage,
            cutoff_freq=cutoff_freq,
            transition_width=transition_width)


class _FilterPlanStage(object):
    def __init__(self, input_rate, output_rate):
        self.input_rate = input_rate
        self.output_rate = output_rate


class _FilterPlanCommentStage(_FilterPlanStage):
    def __init__(self, comment, rate):
        self.comment = comment
        _FilterPlanStage.__init__(self,
            input_rate=rate,
            output_rate=rate)
    
    def create_block(self, taps):
        return None
    
    def calculate_taps(self, final_cutoff, final_transition):
        return None
    
    def explain(self):
        return self.comment


class _FilterPlanXlateStage(_FilterPlanStage):
    def __init__(self, rate, **kwargs):
        _FilterPlanStage.__init__(self,
            input_rate=rate,
            output_rate=rate,
            **kwargs)
    
    def create_block(self, taps):
        return grfilter.freq_xlating_fir_filter_ccc(
            1,
            taps,
            0,
            self.input_rate)
    
    def calculate_taps(self, final_cutoff, final_transition):
        return [1]
    
    def explain(self):
        return 'freq xlation only'


class _FilterPlanDecimatingStage(_FilterPlanStage):
    def __init__(self, freq_xlating, decimation, **kwargs):
        self.freq_xlating = freq_xlating
        self.decimation = decimation
        _FilterPlanStage.__init__(self,
            **kwargs)
    
    def create_block(self, taps):
        assert taps is not None
        if self.freq_xlating:
            return grfilter.freq_xlating_fir_filter_ccc(
                self.decimation,
                taps,
                0,
                self.input_rate)
        else:
            if len(taps) > 10:
                return grfilter.fft_filter_ccc(self.decimation, taps, 1)
            else:
                return grfilter.fir_filter_ccc(self.decimation, taps)
    
    def calculate_taps(self, final_cutoff, final_transition):
        # TODO check for collision with user filter
        user_inner = final_cutoff - final_transition / 2
        limit = self.output_rate / 2
        return firdes.low_pass(
            1.0,
            self.input_rate,
            (user_inner + limit) / 2,
            limit - user_inner,
            firdes.WIN_HAMMING)
    
    def explain(self):
        fx = 'freq xlate and ' if self.freq_xlating else ''
        return '%sdecimate by %i' % (fx, self.decimation,)


class _FilterPlanFinalDecimatingStage(_FilterPlanDecimatingStage):
    def __init__(self, **kwargs):
        _FilterPlanDecimatingStage.__init__(self, **kwargs)

    def calculate_taps(self, final_cutoff, final_transition):
        return firdes.low_pass(
            1.0,
            self.input_rate,
            final_cutoff,
            final_transition,
            firdes.WIN_HAMMING)
    
    def explain(self):
        return 'final filter and ' + super(_FilterPlanFinalDecimatingStage, self).explain()


class _FilterPlanRationalResamplerStage(_FilterPlanStage):
    def __init__(self, decimation, interpolation, **kwargs):
        self.decimation = decimation
        self.interpolation = interpolation
        _FilterPlanStage.__init__(self,
            **kwargs)

    def create_block(self, taps):
        assert taps is not None
        return grfilter.rational_resampler_base_ccf(
            interpolation=self.interpolation,
            decimation=self.decimation,
            taps=taps)
    
    def calculate_taps(self, final_cutoff, final_transition):
        # TODO: This might be internal, and we eventually want to integrate it in the plan anyway
        return rational_resampler.design_filter(
            interpolation=self.interpolation,
            decimation=self.decimation,
            fractional_bw=0.4)
    
    def explain(self):
        return 'rational_resampler by %s/%s (stage rates %s/%s)' % (self.interpolation, self.decimation, self.output_rate, self.input_rate)


class _FilterPlanPfbResamplerStage(_FilterPlanStage):
    def __init__(self, resample_rate, **kwargs):
        self.resample_rate = resample_rate
        _FilterPlanStage.__init__(self,
            **kwargs)
    
    def create_block(self, taps):
        return pfb.arb_resampler_ccf(self.resample_rate)  # TODO explicitly compute taps
    
    def calculate_taps(self, final_cutoff, final_transition):
        return None
    
    def explain(self):
        return 'arb_resampler %s/%s = %s' % (self.output_rate, self.input_rate, float(self.output_rate) / self.input_rate)


def _make_filter_plan_1(input_rate, output_rate):
    assert input_rate > 0
    assert output_rate > 0
    
    total_decimation = max(1, int(input_rate // output_rate))
    
    using_rational_resampler = _use_rational_resampler and input_rate % 1 == 0 and output_rate % 1 == 0
    if using_rational_resampler:
        # If using rational resampler, don't decimate to the point that we get a fractional rate, if possible.
        input_rate = int(input_rate)
        output_rate = int(output_rate)
        if input_rate > output_rate:
            total_decimation = input_rate // small_factor_at_least(input_rate, output_rate)
        # print(input_rate / total_decimation, total_decimation, input_rate, output_rate, input_rate // gcd(input_rate, output_rate))
        # TODO: Don't re-factorize unnecessarily
    
    stage_decimations = factorize(total_decimation)
    stage_decimations.reverse()
    
    # loop variables
    stage_designs = []
    stage_input_rate = input_rate
    last_index = len(stage_decimations) - 1
    
    if len(stage_decimations) == 0:
        # interpolation or nothing -- don't put it in the stages
        freq_xlate_stage = len(stage_designs)
        stage_designs.append(_FilterPlanXlateStage(
            rate=stage_input_rate))
    else:
        # decimation
        for i, stage_decimation in enumerate(stage_decimations):
            next_rate = stage_input_rate / stage_decimation
        
            stage_type = _FilterPlanFinalDecimatingStage if i == last_index else _FilterPlanDecimatingStage
            if i == 0:
                freq_xlate_stage = len(stage_designs)
                stage_designs.append(stage_type(
                    freq_xlating=True,
                    decimation=stage_decimation,
                    input_rate=stage_input_rate,
                    output_rate=next_rate))
            else:
                stage_designs.append(stage_type(
                    freq_xlating=False,
                    decimation=stage_decimation,
                    input_rate=stage_input_rate,
                    output_rate=next_rate))
        
            stage_input_rate = next_rate
    
    # final connection and resampling
    if stage_input_rate == output_rate:
        # exact multiple, no fractional resampling needed
        stage_designs.append(_FilterPlanCommentStage(
            comment='No final resampler stage.',
            rate=output_rate))
    else:
        # TODO: systematically combine resampler with final filter stage
        if using_rational_resampler:
            if stage_input_rate % 1 != 0:
                raise Exception("shouldn't happen", stage_input_rate)
            stage_input_rate = int(stage_input_rate)  # because of float division above
            common = gcd(output_rate, stage_input_rate)
            interpolation = output_rate // common
            decimation = stage_input_rate // common
            stage_designs.append(_FilterPlanRationalResamplerStage(
                interpolation=interpolation,
                decimation=decimation,
                input_rate=stage_input_rate,
                output_rate=output_rate))
        else:
            # TODO: cache filter computation as optfir is used and takes a noticeable time
            stage_designs.append(_FilterPlanPfbResamplerStage(
                resample_rate=float(output_rate) / stage_input_rate,
                input_rate=stage_input_rate,
                output_rate=output_rate))
    
    plan = _MultistageChannelFilterPlan(
        stage_designs=stage_designs,
        freq_xlate_stage=freq_xlate_stage,
        cutoff_freq=-1,
        transition_width=-1)
    
    return plan


class MultistageChannelFilter(gr.hier_block2):
    """
    Provides frequency translation, low-pass filtering, and arbitrary sample rate conversion.
    
    The multistage aspect improves CPU efficiency and also enables high decimations/sharp filters that would otherwise run into buffer length limits. Or at least, those were the problems I was seeing which I wrote this to fix.
    """
    def __init__(self,
            name=b'MultistageChannelFilter',
            input_rate=0,
            output_rate=0,
            cutoff_freq=0,
            transition_width=0,
            center_freq=0):
        # cf. firdes.sanity_check_1f (which is private)
        # TODO better errors for other cases
        cutoff_freq = float(cutoff_freq)
        # TODO coerce output_rate to integer-or-float
        if cutoff_freq > output_rate / 2:
            # early check for better errors since our cascaded filters might be cryptically nonsense
            raise ValueError('cutoff_freq (%s) is too high for output_rate (%s)' % (cutoff_freq, output_rate))
    
        plan = _make_filter_plan_1(
            input_rate=input_rate,
            output_rate=output_rate)
        plan = plan.replace(
            cutoff_freq=cutoff_freq,
            transition_width=transition_width)
        self.__plan = plan
        
        gr.hier_block2.__init__(
            self, str(name),
            gr.io_signature(1, 1, gr.sizeof_gr_complex * 1),
            gr.io_signature(1, 1, gr.sizeof_gr_complex * 1),
        )
        
        self.stages = []
        
        prev_block = self
        for stage_design, taps in plan.get_stage_designs_and_taps():
            stage_filter = stage_design.create_block(taps)
            
            self.stages.append(stage_filter)
            if stage_filter is not None:
                self.connect(prev_block, stage_filter)
                prev_block = stage_filter

        # loop takes care of all connections but the n+1th
        self.connect(prev_block, self)
        
        self.freq_filter_block = self.stages[plan.get_freq_xlate_stage()]
        assert self.freq_filter_block is not None
        self.freq_filter_block.set_center_freq(center_freq)
    
    def __do_taps(self):
        """Re-assign taps for all stages."""
        # TODO: sanity check types:
        #   plan has matching stage types
        #   plan has same decimations
        for stage_filter, (_stage_design, taps) in zip(self.stages, self.__plan.get_stage_designs_and_taps()):
            if hasattr(stage_filter, 'set_taps'):
                stage_filter.set_taps(taps)
    
    def explain(self):
        """Return a description of the filter design."""
        stages = self.stages
        stage_designs = self.__plan.get_stage_designs()
        s = '%s stages from %i to %i' % (
            # TODO use polymorphism instead
            sum(1 for stage_design in stage_designs if not isinstance(stage_design, _FilterPlanCommentStage)),
            stage_designs[0].input_rate,
            stage_designs[-1].output_rate)
        for (stage_filter, stage_design) in zip(stages, stage_designs):
            # TODO once we have pfb converted, stop introspecting on the filter objects and start just using the data from the design
            if hasattr(stage_filter, 'taps'):
                ntaps = len(stage_filter.taps()) if hasattr(stage_filter, 'taps') else 0
                s += '\n  %s using %3i taps (%i) in %s' % (
                    stage_design.explain(),
                    ntaps,
                    stage_design.output_rate * ntaps,
                    type(stage_filter).__name__,)
            elif stage_filter is not None:
                s += '\n  %s using %s' % (
                    stage_design.explain(),
                    type(stage_filter).__name__,)
            else:
                s += '\n  %s' % (
                    stage_design.explain(),)
        return s
    
    def get_cutoff_freq(self):
        return self.__plan.get_cutoff_freq()
    
    def set_cutoff_freq(self, value):
        value = float(value)
        self.__plan = self.__plan.replace(cutoff_freq=value)
        self.__do_taps()
    
    def get_transition_width(self):
        return self.__plan.get_transition_width()
    
    def set_transition_width(self, value):
        value = float(value)
        self.__plan = self.__plan.replace(transition_width=value)
        self.__do_taps()
    
    def get_center_freq(self):
        return self.freq_filter_block.center_freq()
    
    def set_center_freq(self, freq):
        self.freq_filter_block.set_center_freq(freq)
    
    def get_shape(self):
        """Describe the filter shape as a shinysdr.interfaces.BandShape value.
        
        This is primarily a helper for simplifying the code implementing demodulator objects.
        """
        return self.__plan.get_shape()


__all__.append('MultistageChannelFilter')


# TODO: Rename for consistency. Document.
# TODO: Add the ability to memoize/precompute filter taps, particularly because pfb uses optfir internally which is slow. Maybe we can express this using the same 'plan' type as MultistageChannelFilter.
# TODO: I think there are places where we are _not_ using make_resampler because it didn't have a complex mode before.
def make_resampler(in_rate, out_rate, complex=False):
    # pylint: disable=redefined-builtin
    
    fractional_cutoff = 0.4
    fractional_transition_width = 0.2
    
    # The rate relative to in_rate for which to design the anti-aliasing filter.
    in_relative_max_rate = min(out_rate, in_rate) / in_rate
    
    in_relative_cutoff = in_relative_max_rate * fractional_cutoff
    in_relative_transition_width = in_relative_max_rate * fractional_transition_width
    
    if _use_rational_resampler and in_rate % 1 == 0 and out_rate % 1 == 0:
        # Note: rational_resampler has this logic built in, but it does not correctly design the filter when decimating <http://gnuradio.org/redmine/issues/745>, so we do it ourselves; but this also allows sharing the calculation details for pfb_ and rational_.
        in_rate = int(in_rate)
        out_rate = int(out_rate)
        common = gcd(in_rate, out_rate)
        interpolation = out_rate // common
        decimation = in_rate // common
        return (rational_resampler.rational_resampler_ccf if complex else rational_resampler.rational_resampler_fff)(
            interpolation=interpolation,
            decimation=decimation,
            taps=firdes.low_pass(
                interpolation,  # gain compensates for interpolation
                interpolation,  # rational resampler filter runs at the interpolated rate
                in_relative_cutoff,
                in_relative_transition_width))
    else:
        resample_ratio = out_rate / in_rate
        pfbsize = 32  # TODO: justify magic number (taken from gqrx)
        return (pfb.arb_resampler_ccf if complex else pfb.arb_resampler_fff)(
            resample_ratio,
            firdes.low_pass(
                pfbsize,
                pfbsize,
                in_relative_cutoff,
                in_relative_transition_width),
            pfbsize)


__all__.append('make_resampler')


def design_sawtooth_filter(
        ntaps=40,
        decreasing=False,
        window_type=window.WIN_HAMMING,
        beta=0):
    """
    This filter has a response which increases or decreases linearly with frequency, cut at f_s/2. Its gain is 1 at frequency 0 and thus also 1 averaged over all frequencies.
    """
    window_values = window.build(window_type, ntaps, beta)
    
    # Formula provided by Olli Niemitalo in <http://dsp.stackexchange.com/a/28035/4655>.
    taps = []
    for i in six.moves.range(0, ntaps):
        k = i - ntaps // 2  # k = 0 at middle
        if k == 0:
            # substitute limit for division by zero
            ideal_response = complex(pi, 0)
        else:
            # The real part is pi * sinc(k), but that is always zero when k != 0.
            ideal_response = complex(0, sin(pi * k) / (pi * k * k) - cos(pi * k) / k)
        taps.append(window_values[i] * ideal_response)
        
    # Compute gain at frequency 0, and divide by it so as to set the wanted gain.
    gain_factor = 1.0 / abs(sum(taps))
    for i in six.moves.range(0, ntaps):
        taps[i] *= gain_factor
    
    # Reverse if appropriate.
    if decreasing:
        taps = taps[::-1]
    return taps


__all__.append('design_sawtooth_filter')
