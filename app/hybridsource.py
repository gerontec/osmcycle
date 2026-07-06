"""HybridMapSource: offline MBTiles first, live network fetch on miss.

Behaves like a normal OSM tile source (downloads + disk-caches tiles on demand),
but first tries a bundled MBTiles pack so Bayern + Tirol works fully offline.
Tiles the pack doesn't have (higher zooms, neighbouring areas) are pulled from
the network exactly like a standard slippy map.
"""
import io
import sqlite3

from kivy.core.image import Image as CoreImage

from kivy_garden.mapview.downloader import Downloader
from kivy_garden.mapview.source import MapSource

__all__ = ["HybridMapSource"]


class HybridMapSource(MapSource):
    def __init__(self, mbtiles_path, url, **kwargs):
        super().__init__(url=url, **kwargs)
        self.filename = mbtiles_path
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
        # 1) offline: MBTiles stores rows in TMS, same convention as tile.tile_y
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

    def _offline_done(self, tile, im):
        tile.texture = im.texture
        tile.state = "need-animation"
