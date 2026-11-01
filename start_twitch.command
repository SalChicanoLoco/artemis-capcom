#!/bin/bash
# Also works when called from another directory; never requires sudo.
cd -- "$(dirname -- "${BASH_SOURCE[0]}")" || exit 1
exec /usr/bin/env python3 twitch_launcher.py "$@"
