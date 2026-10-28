#!/bin/bash
# Set up Ubuntu 26.04 on a Lenovo Yoga Book YB1-X91L. Run ON THE TABLET:
#
#   sudo tablet/install.sh <dir with linux-image/linux-headers *.deb>
#
# Optional environment:
#   APN=airtelgprs.com   create a NetworkManager mobile-data connection
#   APN_NAME="Airtel LTE"
#
# Safe to re-run.
set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "run with sudo" >&2; exit 1; }
HERE=$(cd "$(dirname "$0")" && pwd)
DEBDIR=${1:?usage: sudo $0 <dir with the kernel .debs>}
KVER=7.2.8-yogabook-cam+
export DEBIAN_FRONTEND=noninteractive

step() { echo; echo "=== $*"; }

step "Ubuntu packages"
apt-get update -q
apt-get install -y -q python3-evdev python3-pyudev iio-sensor-proxy \
  v4l-utils ffmpeg v4l2loopback-dkms v4l2loopback-utils \
  libmbim-utils modemmanager network-manager wget

step "Yoga Book support packages (github.com/jekhor/yogabook-linux)"
# touch-keyboard: Halo keyboard userspace driver; yogabook-support: sensor
# hwdb + modes handler; alsa-ucm-conf-yogabook: sound profiles. Their 6.17
# kernel is not needed with our 7.2.8 kernel (it can stay as a fallback).
REL=https://github.com/jekhor/yogabook-linux/releases/download/debs-20251026
TMP=$(mktemp -d)
for f in touch-keyboard_1.4.3_amd64.deb yogabook-support_1.5.ubuntu1_all.deb \
         alsa-ucm-conf-yogabook_1.4_all.deb; do
  wget -q -O "$TMP/$f" "$REL/$f"
done
dpkg -i --force-depends "$TMP"/*.deb || true
apt-get -f install -y -q
rm -rf "$TMP"

step "Config files and scripts"
# dkms override must be in place before the kernel package triggers a
# v4l2loopback build (the kernel is built with CONFIG_WERROR).
cd "$HERE/files"
find . -type f | while read -r f; do
  dst=/${f#./}
  mode=644; [[ $dst == /usr/local/bin/* ]] && mode=755
  install -D -m "$mode" "$f" "$dst"
  echo "  $dst"
done
install -d /var/lib/yogabook-webcam
[[ -e /var/lib/yogabook-webcam/camera ]] || echo front > /var/lib/yogabook-webcam/camera
chmod 666 /var/lib/yogabook-webcam/camera
# Leftovers from earlier iterations of the webcam setup
rm -f /etc/systemd/system/yogabook-webcam.service \
      /etc/systemd/system/yogabook-webcam-{front,rear}.service \
      /etc/polkit-1/rules.d/50-yogabook-webcam.rules \
      /usr/share/applications/yogabook-camera-off.desktop \
      /etc/modprobe.d/yogabook-modem-test.conf

step "Kernel $KVER"
dpkg -i "$DEBDIR"/linux-image-"$KVER"_*.deb "$DEBDIR"/linux-headers-"$KVER"_*.deb

step "Services, udev, hwdb"
systemctl daemon-reload
systemctl enable yogabook-webcam-watch.service
systemctl --global enable yogabook-landscape-fix.service
systemd-hwdb update
udevadm control --reload

step "GRUB: boot $KVER by default, show the menu for 3 s"
sed -i -e 's/^GRUB_DEFAULT=.*/GRUB_DEFAULT=saved/' \
       -e 's/^GRUB_TIMEOUT_STYLE=.*/GRUB_TIMEOUT_STYLE=menu/' \
       -e 's/^GRUB_TIMEOUT=.*/GRUB_TIMEOUT=3/' /etc/default/grub
update-grub
sub=$(grep -oP "^submenu .*\\\$menuentry_id_option '\\K[^']+" /boot/grub/grub.cfg | head -1)
ent=$(grep -oP "\\\$menuentry_id_option '\\Kgnulinux-\\Q$KVER\\E-advanced-[^']+" /boot/grub/grub.cfg | head -1)
grub-set-default "$sub>$ent"
grub-editenv list

step "Power button: shut down (GNOME asks first), not suspend"
# GNOME suspended on a press (power-button-action 'suspend'), and the battery
# then ran flat in s2idle. 'interactive' shows the Power Off dialog, which
# shuts down by itself after 60 s. Sessions without GNOME (the Living Room
# kiosk) use logind's HandlePowerKey=poweroff.
if [[ -n ${SUDO_USER:-} && $SUDO_USER != root ]]; then
  sudo -u "$SUDO_USER" dbus-run-session gsettings set \
    org.gnome.settings-daemon.plugins.power power-button-action interactive
fi

step "initramfs (it carries modprobe.d options)"
if command -v dracut >/dev/null; then dracut --regenerate-all -f; else update-initramfs -u -k all; fi

if [[ -n ${APN:-} ]]; then
  step "Mobile data connection (APN $APN)"
  name=${APN_NAME:-Mobile data}
  nmcli -t -f NAME connection show | grep -qx "$name" ||
    nmcli connection add type gsm ifname '*' con-name "$name" gsm.apn "$APN"
  nmcli connection modify "$name" connection.autoconnect yes \
    connection.autoconnect-retries 0 ipv4.method auto ipv6.method ignore
fi

step "Done - reboot to use $KVER"
