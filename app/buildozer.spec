[app]
title = OSMCycle
package.name = osmcycle
package.domain = org.gerontec
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,json,mbtiles,gpx
version = 1.4
requirements = python3,kivy==2.3.0,kivy_garden.mapview,requests,certifi,setuptools,sqlite3,plyer,pyjnius
orientation = portrait
fullscreen = 0
android.permissions = INTERNET,ACCESS_NETWORK_STATE,ACCESS_FINE_LOCATION,ACCESS_COARSE_LOCATION,WRITE_EXTERNAL_STORAGE,MANAGE_EXTERNAL_STORAGE,FOREGROUND_SERVICE
android.api = 34
android.minapi = 21
android.ndk = 25b
android.ndk_api = 21
android.archs = arm64-v8a
android.allow_backup = 1
android.accept_sdk_license = True
# Pin p4a to a stable release: builds Python 3.11 (kivy + Cython 0.29 golden
# path). p4a master builds Python 3.14, which kivy 2.3.0's Cython C is not
# compatible with (too few arguments to _PyLong_AsByteArray).
p4a.branch = release-2024.01.21

[buildozer]
log_level = 2
warn_on_root = 1
