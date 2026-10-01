#!/bin/bash
# Turn the Yoga Book into a living-room display. Run ON THE TABLET after
# tablet/install.sh:
#
#   sudo livingroom/install.sh
#
# - "Living Room" kiosk session (cage + WebKit page: clock, weather, animated
#   painted scenes, now playing), auto-login as user "livingroom"
# - Bluetooth speaker "Living Room" (auto-pairing agent), and optionally
#   output to your own Bluetooth speaker (bluetooth_speaker in livingroom.conf)
# - AirPlay receiver (UxPlay) and DLNA renderer (gmediarender)
# - Screen sleep/wake: idle timeout, schedules, camera/light wake-up
# - Miracast receiver (Android / Windows "Cast", Wi-Fi Direct)
# Your GNOME account is untouched: log out of the kiosk to get the login screen.
# Safe to re-run.
set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "run with sudo" >&2; exit 1; }
HERE=$(cd "$(dirname "$0")" && pwd)
export DEBIAN_FRONTEND=noninteractive
step() { echo; echo "=== $*"; }

step "Packages"
apt-get install -y -q sway wlr-randr grim gir1.2-webkit-6.0 gir1.2-gtk-4.0 python3-gi \
  python3-dbus python3-numpy pipewire-bin fonts-noto-color-emoji \
  uxplay i965-va-driver gstreamer1.0-plugins-bad gstreamer1.0-libav avahi-daemon avahi-utils \
  gmediarender bluez swayidle dnsmasq-base gstreamer1.0-plugins-ugly

step "waylandsink fix (screen wake crashed every cast receiver)"
"$HERE/gst-wayland/build.sh"

step "Kiosk user"
id livingroom >/dev/null 2>&1 || useradd -m -c "Living Room" -s /bin/bash livingroom
usermod -aG audio,video,render,bluetooth livingroom
passwd -d livingroom >/dev/null
install -d -o livingroom -g livingroom /home/livingroom/.config/livingroom
for s in autumn snow sakura fireflies rain mountains; do
  install -d -o livingroom -g livingroom "/home/livingroom/Pictures/Living Room/$s"
done

step "Your own pictures (my-pictures/<scene>/ -> ~livingroom/Pictures/Living Room/<scene>/)"
if [[ -d $HERE/my-pictures ]]; then
  for d in "$HERE"/my-pictures/*/; do
    s=$(basename "$d")
    install -d -o livingroom -g livingroom "/home/livingroom/Pictures/Living Room/$s"
    install -o livingroom -g livingroom -m 644 "$d"* "/home/livingroom/Pictures/Living Room/$s/"
  done
fi

step "App and files"
install -d /opt/livingroom
cp -r "$HERE/app/." /opt/livingroom/
rm -rf /opt/livingroom/__pycache__
chmod -R a+rX /opt/livingroom
chmod 755 /opt/livingroom/livingroom.py
cd "$HERE/files"
find . -type f | while read -r f; do
  dst=/${f#./}
  if [[ $dst == /etc/livingroom.conf && -e $dst ]]; then
    # keep your settings; add sections that are new since it was installed
    if ! grep -q '^sleep_after' "$dst"; then
      sed -n '/^# --- Screen power/,$p' "$f" | { echo; cat; } >> "$dst"
      echo "  $dst (kept, screen power settings added)"
    elif ! grep -q '^bluetooth_speaker' "$dst"; then
      sed -n '/^# --- Bluetooth speaker/,$p' "$f" | { echo; cat; } >> "$dst"
      echo "  $dst (kept, Bluetooth speaker setting added)"
    else
      echo "  $dst (kept)"
    fi
    continue
  fi
  mode=644; [[ $dst == /usr/local/bin/* ]] && mode=755
  [[ $dst == /etc/sudoers.d/* ]] && { visudo -cqf "$f" || exit 1; mode=440; }
  install -D -m "$mode" "$f" "$dst"
  echo "  $dst"
done

# touchscreen rotation for the kiosk (72-yogabook-touchscreen-rotate.rules)
udevadm control --reload
udevadm trigger --action=change --subsystem-match=input

step "Session and auto-login"
printf '[User]\nSession=livingroom\nSystemAccount=false\n' > /var/lib/AccountsService/users/livingroom
chmod 600 /var/lib/AccountsService/users/livingroom
C=/etc/gdm3/custom.conf
[[ -e $C.orig ]] || cp "$C" "$C.orig"
sed -i '/^AutomaticLoginEnable=/d; /^AutomaticLogin=/d; /^TimedLogin/d' "$C"
# Automatic login happens once per boot; timed login also logs the kiosk back
# in 10 s after the session ends (e.g. if the compositor crashes).
sed -i '/^\[daemon\]/a AutomaticLoginEnable=True\nAutomaticLogin=livingroom\nTimedLoginEnable=True\nTimedLogin=livingroom\nTimedLoginDelay=10' "$C"

step "Bluetooth speaker"
B=/etc/bluetooth/main.conf
[[ -e $B.orig ]] || cp "$B" "$B.orig"
sed -i -e 's/^#\?Name = .*/Name = Living Room/' \
       -e 's/^#\?Class = .*/Class = 0x240414/' \
       -e 's/^#\?DiscoverableTimeout = .*/DiscoverableTimeout = 0/' \
       -e 's/^#\?AlwaysPairable = .*/AlwaysPairable = true/' \
       -e 's/^#\?FastConnectable = .*/FastConnectable = true/' \
       -e 's/^#\?JustWorksRepairing = .*/JustWorksRepairing = always/' "$B"
systemctl daemon-reload
systemctl restart bluetooth
systemctl enable livingroom-bt-agent.service
systemctl restart livingroom-bt-agent.service

step "Miracast receiver (Wi-Fi Direct)"
systemctl enable --now livingroom-miracast.service

step "Network announcements (AirPlay/DLNA) on Wi-Fi only"
# gmediarender's own system service has no screen or session audio; the kiosk
# session runs it instead.
systemctl disable --now gmediarender.service 2>/dev/null || true
A=/etc/avahi/avahi-daemon.conf
wwan=$(ls /sys/class/net | grep '^ww' | head -1 || true)
if [[ -n $wwan ]]; then
  sed -i "s/^#\?deny-interfaces=.*/deny-interfaces=$wwan/" "$A"
  systemctl restart avahi-daemon
fi

step "Done - reboot (or: sudo systemctl restart gdm) to start the Living Room session"
