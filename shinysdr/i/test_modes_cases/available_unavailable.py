from shinysdr.interfaces import ModeDef
from shinysdr.types import EnumRow

plugin_available = ModeDef(mode='available',
    info=EnumRow(label='expected available'),
    demod_class=object(),
    unavailability=None)

plugin_unavailable = ModeDef(mode='unavailable',
    info=EnumRow(label='expected unavailable'),
    demod_class=object(),
    unavailability='For testing.')
