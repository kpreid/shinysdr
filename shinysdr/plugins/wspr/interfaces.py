from __future__ import division, absolute_import

from zope.interface import Interface


class IWAVIntervalListener(Interface):
    def fileClosed(filename):
        """A recording just finished and the file is closed."""

    def fileOpened(filename):
        """A file was just opened and recording has started."""

    def filename(start_time):
        """Return what the recording should be named.

        `start_time` is in seconds since epoch.
        """
