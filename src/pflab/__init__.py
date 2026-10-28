"""pflab — tax-aware monthly-SIP portfolio research harness for NSE equities."""
__version__ = "0.0.1"

from pflab import release as _release

_release.apply()                 # an installed app's release.toml sets its data, store and channel before anything reads them (S65)
