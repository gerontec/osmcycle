"""OSMCycle - CyclOSM map viewer for Bayern + Tirol (Kivy).

Offline-first: reads a bundled/pushed MBTiles pack so Bayern + Tirol works with
NO network. Higher zooms and neighbouring areas are fetched from the tile server
on demand and disk-cached, exactly like a normal OSM slippy map.
"""
import os

from kivy.app import App
from kivy_garden.mapview import MapView, MapSource

from hybridsource import HybridMapSource

MBTILES_NAME = "bayern-tirol.mbtiles"

# Live CyclOSM tile server, used for on-demand loading (cache misses).
ONLINE_URL = "http://192.168.5.23:8280/tiles/cyclosm/{z}/{x}/{y}.png"

# Bayern + Tirol bounding box (lon_min, lat_min, lon_max, lat_max)
BBOX = (9.9, 46.6, 13.9, 50.6)


def _candidate_paths():
    """Where the offline MBTiles pack might live, most-specific first."""
    paths = []
    # Android: app-specific external files dir -> no runtime permission needed.
    # adb push bayern-tirol.mbtiles \
    #   /sdcard/Android/data/org.gerontec.osmcycle/files/
    try:
        from android import mActivity  # type: ignore
        ext = mActivity.getExternalFilesDir(None)
        if ext:
            paths.append(os.path.join(ext.getAbsolutePath(), MBTILES_NAME))
    except Exception:
        pass
    here = os.path.dirname(os.path.abspath(__file__))
    paths += [
        os.path.join("/sdcard/osmcycle", MBTILES_NAME),
        os.path.join(here, MBTILES_NAME),
        MBTILES_NAME,
    ]
    return paths


def _find_mbtiles():
    for p in _candidate_paths():
        if p and os.path.exists(p):
            return p
    return None


class OSMCycleApp(App):
    def build(self):
        mbt = _find_mbtiles()
        if mbt:
            # Offline pack present + online fallback for anything it lacks.
            source = HybridMapSource(
                mbtiles_path=mbt,
                url=ONLINE_URL,
                cache_key="cyclosm",
                min_zoom=2,
                max_zoom=18,
                tile_size=256,
                image_ext="png",
                attribution="(c) OpenStreetMap contributors, CyclOSM",
            )
        else:
            # No pack: behave as a plain online slippy map.
            source = MapSource(
                url=ONLINE_URL,
                cache_key="cyclosm",
                tile_size=256,
                image_ext="png",
                attribution="(c) OpenStreetMap contributors, CyclOSM",
                min_zoom=2,
                max_zoom=18,
            )
        mapview = MapView(zoom=8, lat=47.5, lon=11.5)
        mapview.map_source = source
        return mapview


if __name__ == "__main__":
    OSMCycleApp().run()
