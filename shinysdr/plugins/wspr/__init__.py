from __future__ import absolute_import, division, unicode_literals

from twisted.python.util import sibpath
from twisted.web import static

from shinysdr.interfaces import ModeDef, ClientResourceDef

from .demodulator import WSPRDemodulator, _find_wsprd

plugin_mode = ModeDef(mode='WSPR',
    info='WSPR',
    demod_class=WSPRDemodulator,
    available=_find_wsprd() is not None)

plugin_client = ClientResourceDef(
    key=__name__,
    resource=static.File(sibpath(__file__, 'client')),
    load_js_path='wspr.js')

__all__ = ['plugin_mode', 'plugin_client']
