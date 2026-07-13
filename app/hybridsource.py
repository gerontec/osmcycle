"""HybridMapSource: offline MBTiles first, live network fetch on miss.

Behaves like a normal OSM tile source (downloads + disk-caches tiles on demand),
but first tries a bundled MBTiles pack so Bayern + Tirol works fully offline.
Tiles the pack doesn't have (higher zooms, neighbouring areas) are pulled from
the network exactly like a standard slippy map.

Two network sources, split by zoom:
  * below hizoom_from: `url` — our own tile.php, which is backed by the very
    same alpen_z15.mbtiles and therefore answers 404 above z15.
  * hizoom_from and up: `hizoom_url` — the public CyclOSM server, the only one
    of the two that actually HAS those zooms. Same rendering style, so nothing
    visibly changes when the map crosses the boundary.
"""
import io
import os
import sqlite3
from random import choice

import requests
from kivy.core.image import Image as CoreImage

from kivy_garden.mapview.downloader import Downloader
from kivy_garden.mapview.source import MapSource

__all__ = ["HybridMapSource", "CYCLOSM_URL", "HIZOOM_FROM"]

CYCLOSM_URL = "https://{s}.tile-cyclosm.openstreetmap.fr/cyclosm/{z}/{x}/{y}.png"
HIZOOM_FROM = 16
# CyclOSM's usage policy expects a User-Agent identifying the app. mapview's
# default names the library ('Kivy-garden.mapview'), which is precisely the kind
# of anonymous traffic such servers throttle.
HIZOOM_USER_AGENT = "OSMCycle (+https://github.com/gerontec/osmcycle)"


class HybridMapSource(MapSource):
    def __init__(self, mbtiles_path, url, hizoom_url=CYCLOSM_URL,
                 hizoom_from=HIZOOM_FROM, hizoom_subdomains="abc", **kwargs):
        super().__init__(url=url, **kwargs)
        self.filename = mbtiles_path          # None: no offline pack at all
        self.hizoom_url = hizoom_url
        self.hizoom_from = hizoom_from
        self.hizoom_subdomains = hizoom_subdomains
        # Read the pack's own zoom range (informational); the source zoom range
        # is kept wide (min_zoom/max_zoom kwargs) so the map can pull higher
        # zooms and neighbouring tiles from the network.
        try:
            db = sqlite3.connect(mbtiles_path)
            meta = dict(db.cursor().execute("SELECT * FROM metadata"))
            db.close()
            self.pack_min_zoom = int(meta.get("minzoom", self.min_zoom))
            self.pack_max_zoom = int(meta.get("maxzoom", self.max_zoom))
        except Exception:
            self.pack_min_zoom, self.pack_max_zoom = self.min_zoom, self.max_zoom

    def fill_tile(self, tile):
        if tile.state == "done":
            return
        Downloader.instance(cache_dir=self.cache_dir).submit(self._hybrid_load, tile)

    def _hybrid_load(self, tile):
        if tile.state == "done":
            return
        # Deliberately keyed on a fixed zoom, NOT on pack_max_zoom: with the
        # bundled mini pack (z0-5) the latter would route every zoom from 6 up
        # to the public CyclOSM server, when tile.php serves those perfectly.
        if tile.zoom >= self.hizoom_from:
            return self._hizoom_load(tile)
        # 1) offline: MBTiles stores rows in TMS, same convention as tile.tile_y
        row = None
        if self.filename:
            try:
                db = sqlite3.connect(self.filename)
                row = db.execute(
                    "SELECT tile_data FROM tiles WHERE "
                    "zoom_level=? AND tile_column=? AND tile_row=?",
                    (tile.zoom, tile.tile_x, tile.tile_y),
                ).fetchone()
                db.close()
            except Exception:
                row = None
        if row:
            try:
                data = io.BytesIO(row[0])
            except Exception:
                data = io.BytesIO(bytes(row[0]))
            im = CoreImage(
                data,
                ext=self.image_ext,
                filename="{}.{}.{}.png".format(tile.zoom, tile.tile_x, tile.tile_y),
            )
            if im is not None:
                return self._offline_done, (tile, im)
        # 2) miss: fall back to the normal network downloader (caches + flips y)
        return Downloader.instance(cache_dir=self.cache_dir)._load_tile(tile)

    def _hizoom_load(self, tile):
        """Downloader._load_tile, but against hizoom_url. That method cannot be
        reused as is: it reads the template off `tile.map_source.url`, so
        serving a second URL by swapping that attribute would race between tiles
        of different zooms fetched concurrently on the downloader's threads."""
        cache_fn = tile.cache_fn
        if os.path.exists(cache_fn):
            return tile.set_source, (cache_fn,)
        tile_y = self.get_row_count(tile.zoom) - tile.tile_y - 1
        uri = self.hizoom_url.format(z=tile.zoom, x=tile.tile_x, y=tile_y,
                                     s=choice(self.hizoom_subdomains))
        try:
            r = requests.get(uri, headers={"User-agent": HIZOOM_USER_AGENT},
                             timeout=5)
            r.raise_for_status()
            with open(cache_fn, "wb") as fd:
                fd.write(r.content)
            return tile.set_source, (cache_fn,)
        except Exception as e:
            # No signal up a mountain is the normal case here, not an error worth
            # shouting about: the tile stays blank until there is a connection.
            print("HybridMapSource: hizoom z{} failed: {!r}".format(tile.zoom, e))

    def _offline_done(self, tile, im):
        tile.texture = im.texture
        tile.state = "need-animation"
