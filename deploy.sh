#!/bin/bash
# Push this setup to the tablet and run tablet/install.sh there.
#
#   ./deploy.sh user@tablet [kernel-deb-dir]
#
# kernel-deb-dir defaults to ~/yb-kernel (output of kernel/build.sh). If it has
# no packages, the prebuilt ones are fetched from this repo's GitHub release.
# Set APN=... to also create the mobile-data connection, e.g.
#   APN=airtelgprs.com APN_NAME="Airtel LTE" ./deploy.sh sumedh@192.168.1.179
set -euo pipefail

HOST=${1:?usage: $0 user@tablet [kernel-deb-dir]}
DEBDIR=${2:-$HOME/yb-kernel}
HERE=$(cd "$(dirname "$0")" && pwd)
RELEASE=${RELEASE:-v7.2.8-yogabook-cam3}

if ! compgen -G "$DEBDIR/linux-image-7.2.8-yogabook-cam+_*.deb" >/dev/null; then
  DEBDIR=$HERE/.debs
  mkdir -p "$DEBDIR"
  echo "Fetching kernel packages from GitHub release $RELEASE"
  gh release download "$RELEASE" --dir "$DEBDIR" --pattern '*.deb' --clobber \
    --repo "$(cd "$HERE" && gh repo view --json nameWithOwner -q .nameWithOwner)"
fi

# Key-based login makes the rest painless.
ssh -o BatchMode=yes "$HOST" true 2>/dev/null || ssh-copy-id "$HOST"

ssh "$HOST" 'rm -rf ~/yogabook-setup && mkdir -p ~/yogabook-setup/debs'
scp -rq "$HERE/tablet" "$HOST:yogabook-setup/"
scp -q "$DEBDIR"/linux-image-7.2.8-yogabook-cam+_*.deb \
       "$DEBDIR"/linux-headers-7.2.8-yogabook-cam+_*.deb "$HOST:yogabook-setup/debs/"
ssh -t "$HOST" "sudo APN='${APN:-}' APN_NAME='${APN_NAME:-}' \
  ~/yogabook-setup/tablet/install.sh ~/yogabook-setup/debs"
echo "Done. Reboot the tablet: ssh $HOST sudo reboot"
