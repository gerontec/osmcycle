#!/usr/bin/env bash
# Pre-render (seed) CyclOSM tiles for the Bayern+Tirol bbox via renderd.
# render_list talks to the renderd socket directly and is multithreaded, so
# this is far faster than fetching tiles one-by-one over HTTP.
#
#   ./seed.sh [MINZOOM] [MAXZOOM]      # defaults 6..13
#
# --all lets render_list take the geographic bbox directly (lon/lat).
# Rule of thumb: seed z6-13; leave z14+ to on-demand live rendering + cache.
set -euo pipefail
MINZ=${1:-6}; MAXZ=${2:-13}
render_list -m cyclosm -s /run/renderd/renderd.sock -n 12 --all \
  -z "$MINZ" -Z "$MAXZ" \
  -w 9.9 -W 13.9 -g 46.6 -G 50.6      # -w/-W lon min/max, -g/-G lat min/max
echo "SEED DONE"
