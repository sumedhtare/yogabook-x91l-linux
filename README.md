# Lenovo Yoga Book YB1-X91L on Ubuntu 26.04

Everything needed to get the Windows Yoga Book (YB1-X91L, Atom x5-Z8550 /
Cherry Trail) working on Ubuntu 26.04: a patched 7.2.8 kernel, config files,
and small helper services. Builds on
[jekhor/yogabook-linux](https://github.com/jekhor/yogabook-linux).

| Hardware | Status | How |
|---|---|---|
| Halo keyboard | ✅ | `touch-keyboard` userspace driver (jekhor) |
| Sound (speakers, headphones, mics) | ✅ | cht-yogabook machine driver (jekhor patches, ported to 7.2) + UCM |
| Auto-rotation | ✅ | fixed sensor hwdb + `yogabook-landscape-fix` |
| Touchscreen, pen, Wi-Fi, battery, kbd backlight | ✅ | upstream |
| Front + rear camera | ✅ | camera patch series + AtomISP + on-demand webcam bridge with white balance |
| LTE modem (XMM7260) | ⚠️ 2G/EDGE only | modem RFC patches + xHCI kept awake |
| Bluetooth | ✅ | firmware patch from Lenovo's Windows driver (`BCM4356A2.hcd`) |
| Suspend/resume with modem/camera | ❓ untested | |

## Replay from scratch

### 1. Tablet: install Ubuntu 26.04

Use a powered micro-USB OTG hub with a USB keyboard and the installer stick,
boot holding **Volume Up**, install normally.

### 2. Laptop: get the kernel packages

Either download the prebuilt ones (GitHub release of this repo), which
`deploy.sh` does automatically, or build them:

```sh
kernel/build.sh            # ~30 min; output in ~/yb-kernel/*.deb
```

`build.sh` fetches linux-7.2.8 from kernel.org (checksum verified), applies
`kernel/patches/*`, uses `kernel/config-7.2.8-yogabook` and runs
`make bindeb-pkg`. Build dependencies are used from the system if installed,
otherwise unpacked locally without root.

### 3. Push to the tablet

```sh
APN=airtelgprs.com APN_NAME="Airtel LTE" ./deploy.sh sumedh@<tablet-ip>
ssh sumedh@<tablet-ip> sudo reboot
```

`deploy.sh` sets up SSH key login, copies `tablet/` and the kernel packages,
and runs `tablet/install.sh` (asks for the tablet's sudo password). Leave out
`APN=` to skip the mobile-data connection. `install.sh` is safe to re-run.

## What `tablet/install.sh` does

1. Ubuntu packages: python3-evdev/pyudev, iio-sensor-proxy, v4l-utils, ffmpeg,
   v4l2loopback-dkms, libmbim-utils, ModemManager.
2. jekhor's packages (release `debs-20251026`): `touch-keyboard`,
   `yogabook-support`, `alsa-ucm-conf-yogabook`.
3. Copies `tablet/files/` to `/` (see below).
4. Installs the kernel, enables the services, rebuilds hwdb.
5. GRUB: `GRUB_DEFAULT=saved`, menu shown 3 s, default = 7.2.8-yogabook-cam+.
   Any other installed kernel stays in "Advanced options" as a fallback.
6. Regenerates all initramfs images (they carry `modprobe.d` options).
7. Optionally creates the NetworkManager GSM connection.

## Files installed on the tablet

| File | Why |
|---|---|
| `etc/udev/hwdb.d/61-sensor-yogabook.hwdb` | Overrides yogabook-support's sensor hwdb: on 7.x the accelerometer ids are `.10/.11/.19/.20`, not `.9/.10/.18/.19`. `.10/.19` = display (no mount matrix — mutter applies the panel rotation itself), `.11/.20` = base. |
| `etc/systemd/user/yogabook-landscape-fix.service`, `usr/local/bin/yogabook-landscape-fix` | Mutter "rotates back to normal" when a keyboard/touchpad appears (Halo keyboard on). "Normal" for this portrait-native panel is portrait, so this puts the screen back to landscape whenever auto-rotation is off. |
| `etc/udev/rules.d/71-yogabook-modem-xhci.rules` | Keeps the xHCI controller, its root hubs and the modem out of runtime suspend. Otherwise the XMM7260 never finishes enumerating (8087:07ef → ~50 s → 8087:0911 MBIM). |
| `etc/udev/rules.d/70-yogabook-atomisp.rules` | Hides the raw AtomISP node (`/dev/video0`) from desktop apps. |
| `etc/modprobe.d/yogabook-webcam.conf`, `etc/modules-load.d/yogabook-webcam.conf` | v4l2loopback `/dev/video10` "Yoga Book Camera", `exclusive_caps=1`, max 1280x720. |
| `etc/dkms/v4l2loopback.conf` | Build v4l2loopback with `-Wno-error=unused-label` (the kernel has `CONFIG_WERROR`). |
| `etc/systemd/system/yogabook-webcam-watch.service`, `usr/local/bin/yogabook-webcam-watch` | On-demand webcam: keeps `/dev/video10` listed, starts the camera when an app opens it, stops it 10 s after the last app closes it. |
| `usr/local/bin/yogabook-webcam` | Camera pipeline: `yogabook-capture` → ffmpeg crop/scale to 1280x720 YUYV. |
| `usr/local/bin/yogabook-capture` | Captures from AtomISP, strips row padding, runs grey-world auto white balance on the ISP white-balance gains and auto exposure on the sensor. |
| `usr/share/applications/yogabook-camera-{front,rear}.desktop` | "Use Front/Rear Camera" launchers (writes `/var/lib/yogabook-webcam/camera`). |

## Kernel patches (`kernel/patches`)

| Patches | Source |
|---|---|
| 0001–0011 | [jekhor/yogabook-linux-kernel](https://github.com/jekhor/yogabook-linux-kernel) branch `v6.18.x-yogabook` (sound, PMIC regulator, pstore). The "WiP atomisp" patch is left out, and patches already upstream in 7.2 (rt5677 ACPI ID/GPIO/reset, drv260x ACPI, PWM2) are dropped. 0004 and 0011 cancel out (kept as upstream has them). |
| 0012–0027 | "media: Add Yoga Book camera support" v7 by Maurizio Casciano ([patchwork series 29791](https://patchwork.linuxtv.org/project/linux-media/list/?series=29791)), not merged upstream yet. |
| 0029 | cht_yogabook machine driver ported to the 7.2 DAPM API (`snd_soc_dapm_to_card`, `snd_soc_card_to_dapm`, `strscpy`). |
| 0030–0031 | RFC "x86/usb: Add Yoga Book XMM7260 modem power sequencing" ([patchwork series 1152088](https://patchwork.kernel.org/project/platform-driver-x86/list/?series=1152088)); the xhci-pci.c include hunk fixed by hand. |
| 0032 | AtomISP: allow the white-balance and black-level private ioctls (upstream disables all private ioctls, so nothing white balances the Bayer data and images are green). |

Config: jekhor's `config-6.17.4-yogabook1` + `make olddefconfig` + camera
(`VIDEO_ATOMISP`, `VIDEO_OV2740`, `VIDEO_OV8858`, `VIDEO_WV517S`,
`IPU_BRIDGE`, `INTEL_SKL_INT3472`), `INTEL_CHT_MODEM`, `USB_NET_CDC_MBIM`,
no `DEBUG_INFO`/`DEBUG_DRIVER`, `LOCALVERSION=-yogabook-cam`.

## Living-room display (`livingroom/`)

Turns the tablet into an always-on living-room screen. `LIVINGROOM=1 ./deploy.sh ...`
or, on the tablet, `sudo livingroom/install.sh`.

- **Kiosk session**: GDM auto-logs in user `livingroom` into the "Living Room"
  Wayland session: [sway](https://swaywm.org) in kiosk mode
  (`/etc/livingroom/sway.conf`: every window full screen, no cursor) running a
  small GTK4/WebKit app (`/opt/livingroom`). GDM timed login brings the kiosk
  back 10 s after the session ends. Log out to reach the normal login screen.
- **Idle screen**: big clock, date, weather (Open-Meteo, location from IP or
  `/etc/livingroom.conf`) over an animated painted scene. Tap the screen for
  the picker: 🍂 autumn, ❄️ snow, 🌸 sakura, ✨ fireflies, 🌧️ rain,
  🏔️ mountains (mist), or Auto (rain when it rains, otherwise by season), and
  the weather card mode (card / small / off). Choices persist in
  `~livingroom/.config/livingroom/state.json`.
- **Paintings**: public-domain works in `app/scenes/<scene>/`
  ([credits](livingroom/app/scenes/CREDITS.md)); drop your own images in
  `~livingroom/Pictures/Living Room/<scene>/` (or `livingroom/my-pictures/<scene>/`
  in this repo, which the installer copies there) and they replace the bundled
  ones for that scene. Currently: autumn path photo, sakura bridge. One image per 20 minutes, slow Ken Burns drift.
- **Bluetooth speaker** "Living Room": always discoverable, pairs without a PIN
  (`livingroom-bt-agent`), class = loudspeaker; track title/artist via AVRCP.
- **AirPlay** (iPhone/iPad/Mac): UxPlay, mirroring full screen with VA-API
  decode, AirPlay audio with title/artist/cover art.
- **DLNA / "Cast to device"** (Windows, Android apps): gmediarender on port
  49494, audio + video, title/artist/art from the sender's metadata.
- **Now playing**: whenever audio plays (any source) a card with the track and
  a small level meter appears. The spectrum visualiser was dropped: too heavy
  for the Atom.
- **Share a laptop screen / extra monitor** (`laptop/`, install with
  `laptop/install.sh` on a GNOME laptop): "Share Screen to Living Room"
  mirrors a screen or window; "Extend to Living Room" makes the display an
  extra 1920x1200 monitor (GNOME virtual monitor via the ScreenCast portal).
  H.264 on the laptop's Intel iGPU (VA-API) + Opus audio over RTP/UDP to
  `livingroom-screen-rx` on the tablet (ports 5600/5602), which shows it full
  screen and returns to the dashboard 3 s after the stream stops. Click the
  launcher again (or `livingroom-share --stop`) to stop.
- **Screen sleep / wake** (`livingroom-power`): set on the display (tap →
  🌙 Screen; saved in `~livingroom/.config/livingroom/power.json`, survives
  reboots) or in the "Screen power" part of `/etc/livingroom.conf`; applied
  within a second: sleep after
  `sleep_after` minutes without a touch, or always on, plus any number of
  `schedule = <days> <HH:MM>-<HH:MM> <on|auto|sleep> [wake_on=...]` lines. A
  dark screen wakes on touch and, per `wake_on`, on camera motion
  (`yogabook-capture --motion`, runs only while dark, ~16 % of one core) or
  a change in room light (ambient light sensors). It never sleeps while
  another device is connected (Bluetooth, an AirPlay/DLNA sender, a cast or
  shared laptop screen). Brightness: auto from the ambient light sensors
  (log scale, ~20 s average, 6-point dead band, 2 s fades - GNOME's version
  followed the sensors' ~4 % noise and kept flickering) or fixed; the
  keyboard backlight is kept off. Both set through logind (no root).
  Dark = sway `output * power off`: panel off, no
  drawing (~8 % CPU in total with the camera watching).
- CPU (Atom x5): idle scene ≈ 45–60 % of one core in WebKit + ~13 % python.

See [NOTES.md](NOTES.md) for findings, gotchas and open issues.
