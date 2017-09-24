# Copyright 2017 Kevin Reid <kpreid@switchb.org>
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
This module contains utilities building on the GNU Radio framework
-- things that could plausibly be part of GNU Radio itself but we
had to write ourselves -- which do not fit into better categories
within the ShinySDR package.
"""

from __future__ import absolute_import, division, unicode_literals

__all__ = []  # appended later


def safe_delete_head_nowait(queue):
    """Like gr.msg_queue.delete_head_nowait, but not crashy.
    
    See https://github.com/gnuradio/gnuradio/issues/976 - delete_head_nowait from Python returns a wrapper object that dereferences a null pointer when used.
    """
    if queue.empty_p():
        return None
    else:
        return queue.delete_head()


__all__.append('safe_delete_head_nowait')
