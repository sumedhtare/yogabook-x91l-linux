#!/bin/bash
# Rebuilds libgstwayland (from gst-plugins-bad, same version as installed)
# with output-done-once.patch and installs it to
# /usr/local/lib/x86_64-linux-gnu, which ld.so searches before /usr/lib.
# Without it every waylandsink (uxplay, gmediarender, screen-rx, miracast)
# crashes when the screen wakes from sleep - an AirPlay sender waking the
# screen killed its own connection. Run with sudo; ~1 min on the tablet.
# Re-run after an Ubuntu update of libgstreamer-plugins-bad1.0-0.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "run with sudo" >&2; exit 1; }
HERE=$(cd "$(dirname "$0")" && pwd)
V=$(dpkg-query -W -f '${source:Upstream-Version}' libgstreamer-plugins-bad1.0-0)
LIB=/usr/local/lib/x86_64-linux-gnu
SO=libgstwayland-1.0.so.0.$(echo "$V" | awk -F. '{printf "%d%02d.0", $2, $3}')
apt-get install -y -q meson ninja-build pkg-config gcc wget libgstreamer1.0-dev \
  libgstreamer-plugins-base1.0-dev libwayland-dev wayland-protocols libdrm-dev
W=$(mktemp -d)
trap 'rm -rf "$W"' EXIT
cd "$W"
wget -q "https://gstreamer.freedesktop.org/src/gst-plugins-bad/gst-plugins-bad-$V.tar.xz"
tar xf "gst-plugins-bad-$V.tar.xz"
cd "gst-plugins-bad-$V"
patch -p1 < "$HERE/output-done-once.patch"
meson setup build --buildtype=release -Dauto_features=disabled -Dwayland=enabled -Dexamples=disabled \
  -Dtests=disabled -Dintrospection=disabled -Dnls=disabled -Dorc=disabled >/dev/null
ninja -C build "gst-libs/gst/wayland/$SO"
rm -f "$LIB"/libgstwayland-1.0.so.0*
install -D -s -m 644 "build/gst-libs/gst/wayland/$SO" "$LIB/$SO"
ln -sf "$SO" "$LIB/libgstwayland-1.0.so.0"
ldconfig
echo "installed $LIB/$SO (patched gst-plugins-bad $V)"
