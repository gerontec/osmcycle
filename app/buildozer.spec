[app]
title = OSMCycle
package.name = osmcycle
package.domain = org.gerontec
source.dir = .
source.include_exts = py,png,jpg,kv,atlas
version = 0.1
requirements = python3,kivy==2.3.0,kivy_garden.mapview,requests,certifi,pillow,setuptools
orientation = portrait
fullscreen = 0
android.permissions = INTERNET,ACCESS_NETWORK_STATE
android.api = 34
android.minapi = 21
android.ndk_api = 21
android.archs = arm64-v8a
android.allow_backup = 1
android.accept_sdk_license = True
p4a.branch = master

[buildozer]
log_level = 2
warn_on_root = 1
