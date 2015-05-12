# Copyright 2015 Kevin Reid <kpreid@switchb.org>
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

'''
GNU Radio blocks which automatically compute appropriate filter designs.
'''

from __future__ import absolute_import, division

from fractions import gcd

from gnuradio import gr
from gnuradio import filter as grfilter  # don't shadow builtin
from gnuradio.filter import pfb
from gnuradio.filter import firdes
from gnuradio.filter import rational_resampler

from shinysdr.math import factorize, small_factor_at_least


__all__ = []  # appended later

# Use rational_resampler_ccf rather than arb_resampler_ccf. This is less efficient, but avoids the bug <http://gnuradio.org/redmine/issues/713> where the latter block will hang the flowgraph if it is reused. When that is fixed, turn this flag off and maybe ditch the code for it.
_use_rational_resampler = True


class MultistageChannelFilter(gr.hier_block2):
    '''
    Provides frequency translation, low-pass filtering, and arbitrary sample rate conversion.
    
    The multistage aspect improves CPU efficiency and also enables high decimations/sharp filters that would otherwise run into buffer length limits. Or at least, those were the problems I was seeing which I wrote this to fix.
    '''
    def __init__(self,
            name='Multistage Channel Filter',
            input_rate=0,
            output_rate=0,
            cutoff_freq=0,
            transition_width=0,
            center_freq=0):
        assert input_rate > 0
        assert output_rate > 0
        assert cutoff_freq > 0
        assert transition_width > 0
        # cf. firdes.sanity_check_1f (which is private)
        # TODO better errors for other cases
        if cutoff_freq > output_rate / 2:
            # early check for better errors since our cascaded filters might be cryptically nonsense
            raise ValueError('cutoff_freq (%s) is too high for output_rate (%s)' % (cutoff_freq, output_rate))
        
        gr.hier_block2.__init__(
            self, name,
            gr.io_signature(1, 1, gr.sizeof_gr_complex * 1),
            gr.io_signature(1, 1, gr.sizeof_gr_complex * 1),
        )
        
        self.cutoff_freq = cutoff_freq
        self.transition_width = transition_width
        
        total_decimation = max(1, int(input_rate // output_rate))
        
        using_rational_resampler = _use_rational_resampler and input_rate % 1 == 0 and output_rate % 1 == 0
        if using_rational_resampler:
            # If using rational resampler, don't decimate to the point that we get a fractional rate, if possible.
            input_rate = int(input_rate)
            output_rate = int(output_rate)
            if input_rate > output_rate:
                total_decimation = input_rate // small_factor_at_least(input_rate, output_rate)
            # print input_rate / total_decimation, total_decimation, input_rate, output_rate, input_rate // gcd(input_rate, output_rate)
            # TODO: Don't re-factorize unnecessarily
        
        stage_decimations = factorize(total_decimation)
        stage_decimations.reverse()
        
        self.stages = []
        
        # loop variables
        prev_block = self
        stage_input_rate = input_rate
        last_index = len(stage_decimations) - 1
        
        if len(stage_decimations) == 0:
            # interpolation or nothing -- don't put it in the stages
            # TODO: consider using rotator block instead (has different API)
            self.freq_filter_block = grfilter.freq_xlating_fir_filter_ccc(
                1,
                [1],
                center_freq,
                stage_input_rate)
            self.connect(prev_block, self.freq_filter_block)
            prev_block = self.freq_filter_block
        else:
            # decimation
            for i, stage_decimation in enumerate(stage_decimations):
                next_rate = stage_input_rate / stage_decimation
            
                if i == 0:
                    stage_filter = grfilter.freq_xlating_fir_filter_ccc(
                        stage_decimation,
                        [0],  # placeholder
                        center_freq,
                        stage_input_rate)
                    self.freq_filter_block = stage_filter
                else:
                    taps = self.__stage_taps(i == last_index, stage_input_rate, next_rate)
                    if len(taps) > 10:
                        stage_filter = grfilter.fft_filter_ccc(stage_decimation, taps, 1)
                    else:
                        stage_filter = grfilter.fir_filter_ccc(stage_decimation, taps)
            
                self.stages.append((stage_filter, stage_input_rate, next_rate))
            
                self.connect(prev_block, stage_filter)
                prev_block = stage_filter
                stage_input_rate = next_rate
        
        # final connection and resampling
        if stage_input_rate == output_rate:
            # exact multiple, no fractional resampling needed
            self.connect(prev_block, self)
            self.__resampler_explanation = 'No final resampler stage.'
        else:
            # TODO: systematically combine resampler with final filter stage
            if using_rational_resampler:
                if stage_input_rate % 1 != 0:
                    raise Exception("shouldn't happen", stage_input_rate)
                stage_input_rate = int(stage_input_rate)  # because of float division above
                common = gcd(output_rate, stage_input_rate)
                interpolation = output_rate // common
                decimation = stage_input_rate // common
                self.__resampler_explanation = 'rational_resampler by %s/%s (stage rates %s/%s)' % (interpolation, decimation, output_rate, stage_input_rate)
                resampler = rational_resampler.rational_resampler_ccf(
                    interpolation=interpolation,
                    decimation=decimation)
            else:
                # TODO: cache filter computation as optfir is used and takes a noticeable time
                self.__resampler_explanation = 'arb_resampler %s/%s = %s' % (output_rate, stage_input_rate, float(output_rate) / stage_input_rate)
                resampler = pfb.arb_resampler_ccf(float(output_rate) / stage_input_rate)
            self.connect(
                prev_block,
                resampler,
                self)
        
        # TODO: Shouldn't be necessary since we compute the taps in the loop above...
        self.__do_taps()
    
    def __do_taps(self):
        '''Re-assign taps for all stages.'''
        last_index = len(self.stages) - 1
        for i, (stage_filter, stage_input_rate, stage_output_rate) in enumerate(self.stages):
            stage_filter.set_taps(self.__stage_taps(i == last_index, stage_input_rate, stage_output_rate))
    
    def __stage_taps(self, is_last, stage_input_rate, stage_output_rate):
        '''Compute taps for one stage.'''
        cutoff_freq = self.cutoff_freq
        transition_width = self.transition_width
        if is_last:
            return firdes.low_pass(
                1.0,
                stage_input_rate,
                cutoff_freq,
                transition_width,
                firdes.WIN_HAMMING)
        else:
            # TODO check for collision with user filter
            user_inner = cutoff_freq - transition_width / 2
            limit = stage_output_rate / 2
            return firdes.low_pass(
                1.0,
                stage_input_rate,
                (user_inner + limit) / 2,
                limit - user_inner,
                firdes.WIN_HAMMING)
    
    def explain(self):
        '''Return a description of the filter design.'''
        if len(self.stages) > 0:
            s = '%s stages from %i to %i' % (len(self.stages), self.stages[0][1], self.stages[-1][2])
        else:
            s = 'interpolation only'
        for stage_filter, stage_input_rate, stage_output_rate in self.stages:
            s += '\n  decimate by %i using %3i taps (%i) in %s' % (
                stage_input_rate // stage_output_rate,
                len(stage_filter.taps()),
                stage_output_rate * len(stage_filter.taps()),
                type(stage_filter).__name__)
        s += '\n' + self.__resampler_explanation
        return s
    
    def get_cutoff_freq(self):
        return self.cutoff_freq
    
    def set_cutoff_freq(self, value):
        self.cutoff_freq = float(value)
        self.__do_taps()
    
    def get_transition_width(self):
        return self.transition_width
    
    def set_transition_width(self, value):
        self.transition_width = float(value)
        self.__do_taps()
    
    def get_center_freq(self):
        return self.freq_filter_block.center_freq()
    
    def set_center_freq(self, freq):
        self.freq_filter_block.set_center_freq(freq)


__all__.append('MultistageChannelFilter')


# TODO: Rename for consistency. Document.
def make_resampler(in_rate, out_rate):
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
        return rational_resampler.rational_resampler_fff(
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
        return pfb.arb_resampler_fff(
            resample_ratio,
            firdes.low_pass(
                pfbsize,
                pfbsize,
                in_relative_cutoff,
                in_relative_transition_width),
            pfbsize)


__all__.append('make_resampler')
