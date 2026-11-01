#!/bin/bash
# Rehearse the complete experience with no Twitch account or model download.
cd -- "$(dirname -- "${BASH_SOURCE[0]}")" || exit 1
exec /usr/bin/env python3 lunar_copilot.py --no-model --serve --open "$@"
