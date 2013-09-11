Web SDR Application (name pending)
==================================

This is the software component of a software-defined radio receiver. When combined with hardware devices such as the USRP, RTL-SDR, or HackRF, it can be used to listen to a wide variety of radio transmissions, and can be extended via plugins to support even more modes.

Notable features:

* **Browser-based UI:** The receiver can be listened to and remotely controlled over a network or the Internet, as well as from the same machine the actual hardware is connected to.

* **Modularity**: plugin system allows adding support for new modes (types of modulation) and hardware devices.

* **“Hackability”**: All server code is Python, and has no mandatory build or install step. Demodulators prototyped in GNU Radio Companion can be turned into plugins with very little additional code. Control UI can be automatically generated or customized and is based on a generic networking layer.

* **Persistent waterfall display**: You can zoom, pan, and retune without losing any history. (Yes, this is a major bullet point. I haven't met another app that does this, not that I've looked hard.)

* **Frequency database**: Jump to favorite stations; catalog signals you hear; import published band, channel, and station info; take notes. (Note: Writing changes to disk is **not yet implemented**.)

Setup
-----

Dependencies:

* Install the following software on the server:
    * Python 2.7 or later compatible version.
    * GNU Radio 3.7.1 or later.
    * `gr-osmosdr`, and any applicable hardware drivers such as `librtlsdr`. (Plugins may be written to use other RF sources, but the only built-in support is for `gr-osmosdr`.)
* In the `sdr/deps/` directory, copy or symlink the following items:
    * `jasmine/` (Jasmine 1.3.1 or later)
    * `openlayers/` (OpenLayers 2.13.1 or later)
    * `require.js` (RequireJS 2.1.8 or later)
* Google Chrome is currently required for the user interface. While it is not intended to be specifically Chrome-only, no attempt has been made to avoid using facilities which are not yet implemented in other browsers.

The server uses a configuration file, which is Python code.
Run <code>python -m sdr.main --create <var>filename</var></code> to create an example file.
Edit it to specify your available hardware and other desired configuration (such as a HTTPS server certificate).


Running
-------

Once you have prepared a configuration file, you can run the server using <code>python -m sdr.main <var>filename</var></code> and access it using your browser at the displayed URL.


Creating plugins
----------------


TODO explain extensibility points

TODO show how to add plugins to the path

TODO link to Twisted plugin docs


Copyright and License
---------------------

TODO