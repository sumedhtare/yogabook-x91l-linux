#!/bin/sh
# Install "Share to Living Room" for the current user (no root needed).
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
install -D -m 755 "$HERE/livingroom-share" "$HOME/.local/bin/livingroom-share"
for f in "$HERE"/livingroom-share-*.desktop; do
  install -D -m 644 "$f" "$HOME/.local/share/applications/$(basename "$f")"
done
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
echo "Installed: livingroom-share, 'Share Screen to Living Room', 'Extend to Living Room'"
