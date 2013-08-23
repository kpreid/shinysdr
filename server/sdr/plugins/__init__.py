# per https://twistedmatrix.com/documents/current/core/howto/plugin.html
from twisted.plugin import pluginPackagePaths
__path__.extend(pluginPackagePaths(__name__))
__all__ = []
