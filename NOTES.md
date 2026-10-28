# Notes, findings and open issues

## Cameras

- Front: OmniVision OV2740 (ACPI `OVTI2740`), rear: OV8858 (`INT3477`) with
  WV517S focus motor, both on the Cherry Trail AtomISP2 (`8086:22b8`).
- ISP firmware `intel/ipu/shisp_2401a0_v21.bin` ships in Ubuntu's
  linux-firmware.
- `/dev/video0` has input 0 = front (1916x1076), input 1 = rear (1616x1208),
  rows padded to a multiple of 32 pixels, and it can only be opened once.
- No 3A without Intel's proprietary userspace. Raw OV2740 Bayer data is
  R/G≈0.57, B/G≈0.58; the ISP white-balance gains default to 1.0 and the
  sensor's own `red/blue_balance` is weak (4x gives only +23%), hence the
  green images. `yogabook-capture` sets the ISP gains
  (`ATOMISP_IOC_S_ISP_WHITE_BALANCE`, 1.15 fixed point); the front camera
  settles around r≈1.7–1.8, b≈1.7–1.8. `ATOMISP_IOC_S_BLACK_LEVEL_COMP` had
  no visible effect.
- The first capture after boot takes 25 s+ (ISP bring-up); the watcher warms
  the camera up once at boot.
- The Windows driver package (Lenovo DS119820,
  `yoga_book_intel_chipset_driver_201804.zip`,
  `Intel_Driver/Camera/ov2740/OV2740_CJAE533_CHT.cpf` and
  `ov8858/OV8858_P8V12F203_CHT.cpf`) has Intel's AIQB tuning: a chain of
  `<u32 size><u16 tag><u16 id>` records — ids 1–20 camera-module data (2 =
  resolution/bit depth, 3 = black level, 5 = saturation, 10 = lens shading,
  15 = colour matrices), 257+ = 3A tuning, 321+ = ISP settings (324 looks
  like a gamma curve). Colour matrix / gamma / lens shading are not decoded
  or applied yet. Not redistributed here (Lenovo/Intel files).

### Webcam bridge gotchas

- GStreamer (Cheese) skips V4L2 devices that announce both capture and
  output, so v4l2loopback needs `exclusive_caps=1`.
- With `exclusive_caps=1`, capture formats are only offered while a writer is
  attached, and a second writer gets `VIDIOC_G_FMT: EINVAL`. So the watcher is
  the one and only writer: it holds the output side open, writes a
  placeholder frame, and copies the camera frames in.
- v4l2loopback replays the last frame to new readers — hence the placeholder.
- udev probes the device before the writer exists; the watcher re-triggers
  udev (remove + add; PipeWire ignores "change").
- `v4l2-ctl -i N` prints "Video input set to ..." on stdout, which corrupts
  `--stream-to=-`.
- dracut copies `modprobe.d` into the initramfs: regenerate it after changing
  module options.
- WirePlumber only lets the user on the active seat stream cameras; PipeWire
  camera tests over SSH fail when nobody is logged in on the tablet.
- libcamera 0.7 (Ubuntu 26.04) has no AtomISP support, so the Windows-like
  model (app opens the camera, the stack runs 3A, no watcher/loopback) is not
  available yet.

## LTE modem (Intel XMM7260)

- Sits on the Cherry Trail xHCI SSIC port, ACPI `INT34D0`. Firmware
  `BLADE7260_MBIM_ES3_01.1625.00`, `XMM7260_V2_REV_3.0_NAND_MBIM`.
- The `intel_cht_modem` driver powers it on (PMIC reg 0x6e29 + ACPI `_DSM`).
  It first shows up as 8087:07ef and ~50 s later as 8087:0911 (MBIM,
  `cdc-wdm0` + `wwp0s20u5`) — only if xHCI and its root hubs never runtime
  suspend (udev rule).
- ModemManager 1.25 handles it with the Fibocom plugin (can't be overridden).
  The first connect sometimes fails with "MBIM status error: Failure"; the
  NetworkManager retry succeeds.
- Only GPRS/EDGE was ever offered (Airtel India, which has no 3G), although
  the modem advertises LTE and the YB1-X91L spec lists bands 1/3/8/40. The
  firmware exposes no way to set RAT/bands (no AT tunnel, no ATDS RAT, no LTE
  attach config); 13 unknown vendor MBIM services may hold that.
- It once crashed into Comneon dump mode (1519:f000) while trying odd APNs.
  Recover: `sudo modprobe -r intel_cht_modem && sudo modprobe intel_cht_modem`
  or reboot.

## Rotation

- The panel is 1200x1920 portrait-native (kernel quirk `rightside_up`), and
  mutter applies the sensor orientation relative to the panel's native
  orientation — so the display accelerometers need no mount matrix.
- Mutter only auto-rotates in touch mode; with the Halo keyboard's virtual
  touchpad present it leaves touch mode and resets to the CRTC-native
  (portrait) orientation — `yogabook-landscape-fix` undoes that.

## Other

- `cherryview-pinctrl INT33FF:04 probe failed -61`, `intel-hid failed to
  enable HID power button`: harmless.
- Bluetooth firmware patch `brcm/BCM4356A2.hcd` (installed from `tablet/files`)
  = `BCM4356A2_001.003.015.0102.0307.hcd` from Lenovo's Windows Bluetooth driver
  (`yoga_book_bluetooth_201702.zip`, DS119810; `BtwSerialBus.inf` maps
  `ACPI\BCM2E8A` -> this file for Windows 10). Loads as "BCM4356 37.4MHz Lenovo
  Yeti-0102 build 0307".
- Bluetooth audio (A2DP from an iPhone) was robotic and dropped after a few
  seconds while Wi-Fi was on 2.4 GHz: the BCM4356 shares one radio between
  Wi-Fi and BT, and PipeWire logged "client missed wakeups" on the bluez
  input. Use the router's 5 GHz network. That needs the Wi-Fi regulatory
  domain set (`/etc/modprobe.d/cfg80211-regdom.conf`, IN): with the default
  world domain 5 GHz channels are passive-scan only. The Windows Wi-Fi
  driver (yoga_book_wifi_201707.zip) has no NVRAM/btc settings to borrow.
  5 GHz alone was not enough: what fixed it was
  `livingroom/files/etc/wireplumber/wireplumber.conf.d/51-livingroom-audio.conf`
  — SST speaker `api.alsa.headroom = 2048` (was 0; the sink's ERR count kept
  climbing) and `node.latency = 4096/48000` for `bluez_input.*`. After a
  Bluetooth firmware/driver reload, restart WirePlumber in the kiosk session
  and re-pair the phone.
- jekhor's kernel 6.17.4-yogabook1 can stay installed as a fallback (sound
  works there too; cameras/modem don't).

## Living-room display

- Compositor: started with cage 0.2.1, but it crashes
  (`wlr_xdg_surface_schedule_configure: Assertion surface->initialized`) as
  soon as a second window appears — i.e. every AirPlay/DLNA video — killing
  the session. Replaced by sway with a kiosk config. sway counts output
  transforms clockwise: `transform 270` = wlr-randr's `90`. GDM TimedLogin
  re-logs the kiosk in if the session ever dies (AutomaticLogin fires only
  once per boot).
- Without portals (`GDK_DEBUG=no-portals`, else GTK waits ~25 s for a portal
  that never comes) GTK derives the DPI from the panel's physical size
  (226 dpi) and WebKit zooms the page 2.35x: pin `gtk-xft-dpi` to 96.
- `GSK_RENDERER=ngl`: the Vulkan (hasvk) path is flaky on Cherry Trail.
- Touch: wlroots/cage does not rotate absolute touch coordinates with the
  output transform, so taps landed in the wrong place (the first tap "worked"
  because the picker opens anywhere). udev sets
  `LIBINPUT_CALIBRATION_MATRIX=0 -1 1 1 0 0` on the HDP0001 touchscreen;
  mutter sets its own matrix, so GNOME is unaffected. Taps are logged to the
  session journal (`livingroom: tap [...]`).
- CPU budget: 60 fps CSS animations of large layers and a full-screen canvas
  spectrum were too heavy (WebKit ~100 %); particles are drawn on a
  half-resolution canvas at 24 fps, the painting drift is `steps()` at 5/s.
- Audio level: `pw-record -P '{ stream.capture.sink=true }'` on the default
  sink's monitor, 8 kHz mono, RMS 10x/s (1x/s during silence).
- gmediarender's own system service must stay disabled (no display/session
  audio there); Avahi is kept off the mobile-data interface.
- AirPlay mirroring gave sound but a blank (black, full-screen) window. Two
  causes: UxPlay's default audio/video sync dropped every frame as late
  (`-vsync no`), and the i965 VA-API H.264 decoder produces black frames for
  iPhone mirror streams without reporting an error (`-avdec`, software
  decoding). Test pipelines with x264enc-encoded streams decode fine in
  hardware, so this only shows with a real iPhone. Also: the receiver loops
  must end with the session (`kill -0 $ME`), otherwise orphaned uxplay
  instances from an old session keep advertising "Living Room" and grab
  connections with no screen to draw on.
- Laptop screen sharing: on the hybrid Intel+NVIDIA laptop the GStreamer VA
  plugin probed the NVIDIA device and registered no elements; with
  `LIBVA_DRIVER_NAME=iHD` (+ a private `GST_REGISTRY`, since the default
  registry caches the empty result) `vah264lpenc` appears. Portal
  `AvailableSourceTypes` = 7 includes VIRTUAL (4): mutter creates a
  virtual monitor sized by the consumer's caps (request 1920x1200 right after
  `pipewiresrc`). Receiver decodes in software (~1 core for 1920x1200@30).
  Gotchas: (1) mutter only sends a frame when something changed (otherwise
  empty buffers that pipewiresrc drops: "Buffer is empty"), so a still
  desktop sent nothing and the receiver timed out -> `pipewiresrc
  keepalive-time=500` repeats the last frame, `videorate` makes 30 fps. (A
  live `compositor` canvas for this silently discarded the late screen frames
  and froze the picture.) (2) GNOME 50: the portal's virtual-monitor stream
  only ever contains the wallpaper - windows on the virtual monitor are
  missing, though frames arrive while they move. Recording the same monitor
  with `org.gnome.Mutter.ScreenCast` RecordMonitor("Meta-N") shows everything,
  so the portal stream is only kept (into a fakesink) to hold the virtual
  monitor, and the picture comes from RecordMonitor (allowed for session
  clients, no dialog). Verified by decoding a tablet-side pcap while changing
  the wallpaper colour. GNOME closes RecordMonitor sessions whenever the
  display layout changes (monitor unplugged, the virtual one being placed):
  the sender listens for the Session "Closed" signal and records again.
  (2b) The real reason the tablet never moved: the laptop has no `pactl`, so
  the sender sent no audio, and the receiver pipeline (video + audio sinks)
  never finished its async state change -> waylandsink showed the preroll
  frame forever. Receiver sinks are now async=false / async-handling, and
  the sender uses `pulsesrc device=@DEFAULT_MONITOR@`. Test the TABLET screen
  (grim as livingroom, WAYLAND_DISPLAY=wayland-1), not just a pcap. (3) the
  virtual monitor ("Meta-0, Virtual remote monitor") is created but not added
  to the logical layout, so the pointer/windows can't reach it -> the sender
  places it right of the existing monitors via DisplayConfig
  ApplyMonitorsConfig (temporary method, not saved).
- Screen power: sway turning the output back on (`output * power on`, or
  wlopm DPMS on) made every GStreamer waylandsink in the session segfault
  (thread GstWlDisplay, "segfault at ffffffffffffffa8 ... in libglib").
  NOT harmless: an AirPlay sender connecting while the screen sleeps wakes it
  and uxplay died mid-connection ("AirPlay stopped working", 2026-10-01).
  Cause: GStreamer 1.28.2 (still in main) output_done() uses
  g_object_steal_data(output, "display"), so the second "done" event that
  sway sends on power-on gets NULL -> g_mutex_lock(NULL+0x58). Known
  upstream, unfixed: gstreamer#5144, #5329 (MR !11778 closed unmerged). Fix
  (output-done-once.patch) returns early on the repeated done; do NOT just
  switch steal_data to get_data - re-running g_hash_table_replace() with the
  same output unrefs it via the table's value destroy (use-after-free). Fix:
  livingroom/gst-wayland (patch + build.sh -> patched libgstwayland in
  /usr/local/lib/x86_64-linux-gnu, found before /usr/lib; re-run build.sh
  after an Ubuntu update of libgstreamer-plugins-bad1.0-0).
  Tried and rejected: glimagesink survives power cycles, but the tablet
  hard-froze (no log) the first time an iPhone connected to it while the
  screen woke. Backlight 0 / bl_power=4 do not darken this panel (it still
  glows); only output power off / DPMS does.
  Touch is detected with swayidle (`timeout 1 'echo idle' resume 'echo
  active'`) since the kiosk user can't read /dev/input. Camera motion needs
  the root-only AtomISP node -> sudoers rule for exactly
  `yogabook-capture front|rear --motion`; the webcam bridge (/dev/video10)
  would cost ~1.6 cores (ffmpeg scaling), `--motion` only compares a
  120x45 grid of Y samples 3x a second (noise ~0.3 % changed, trigger 3 %).
  Receiver audio sink: `autoaudiosink async-handling=true` spins at ~90 %
  CPU with no audio; `pulsesink async=false` doesn't.
- Miracast / Wi-Fi Direct on this tablet (brcmfmac BCM4356 + the
  NetworkManager-run wpa_supplicant):
  * NetworkManager deletes every P2P group interface it did not create
    ("NMSupplicantInterface is disposing (remove in wpa_supplicant)"), even
    with the P2P device unmanaged -> groups made with wpa_cli die within a
    second after WPS. So the connection must be made by NetworkManager: on
    a sender's P2P-GO-NEG-REQUEST (seen on the wpa_supplicant control
    socket) livingroom-miracast activates a temporary wifi-p2p connection
    to that peer. NetworkManager negotiates with GO intent 7, so either side
    can become owner; as owner it shares (its own dnsmasq, lease file
    /var/lib/NetworkManager/dnsmasq-<iface>.leases gives the sender's IP).
  * Discoverability: NetworkManager StartFind (listens between searches).
    P2P_EXT_LISTEN 500/2000 was too little for a sender to find the tablet.
  * An autonomous GO (P2P_GROUP_ADD) is found but NetworkManager/Android
    senders negotiate instead of joining; and the firmware moved a 2.4 GHz
    GO to the station's 5 GHz channel right after WPS (client: beacon loss).
  * Reliability with the laptop stand-in: ~2/3; failures are negotiation
    timeouts, the sender's retry usually works.

- Bluetooth audio stalls (~1 s) from a Pixel 5: it picked aptX HD (no error
  recovery, 576 kbit/s) and livingroom-miracast's continuous Wi-Fi Direct
  search kept hopping the shared radio onto 2.4 GHz. Fix: WirePlumber
  bluez5.codecs = [ aac sbc_xq sbc ] (Ubuntu has no AAC plugin -> SBC) and
  livingroom-miracast pauses discovery while an A2DP transport is active.

- Bluetooth speaker output (`bluetooth_speaker = <name|address>` in
  livingroom.conf): livingroom-bt-agent (root) polls the kiosk's PipeWire
  every 3 s (`PIPEWIRE_RUNTIME_DIR=/run/user/<uid> pw-dump Node`, ~40 ms;
  ~1.8 % of a core in all, nothing while the setting is empty) for a running
  Stream/Output/Audio whose process command line is uxplay, gmediarender,
  livingroom-screen-rx or the Miracast gst-launch (rtpmp2tdepay). Nodes carry
  no process id: it is on the client object (`pw-dump <client.id>`). Only then it connects the speaker (discovering BR/EDR and
  pairing Just Works first if needed, retry every 30 s); 60 s after the last
  running stream it disconnects it, also when the speaker connected by
  itself. A phone's A2DP audio is deliberately not relayed (two A2DP links on
  the one shared radio), and no paging/discovery happens while a phone
  streams. WirePlumber bluez_output priority 3000 > SST speaker, so it
  becomes the default sink and streams follow it
  (linking.follow-default-target). livingroom-power ignores Bluetooth devices
  of major class audio/video, so the speaker never counts as a connected
  phone. Tested 2026-10-01 with silent pw-cat streams (argv0 "uxplay-test"
  starts it, any other stream does not, discovery stops 60 s after); not
  yet with a real speaker.
  Speaker panel (picker -> 🔊 Speaker): livingroom.py scans/pairs/forgets
  over BlueZ D-Bus itself (the D-Bus policy allows any user; pairing uses
  the root agent as default agent) and writes
  ~livingroom/.config/livingroom/speaker.json {address, name, enabled},
  which the agent prefers over bluetooth_speaker/_enabled in the conf.
  Off = agent treats it as never playing (disconnects it, no pw-dump).

- Touch: WebKitGTK follows every touch pointerdown with an emulated mouse
  pointerdown at the same spot 0.1-0.5 s later (tap log: 'touch' then
  'mouse'). The page handled both, so a button opening a panel had it closed
  again by the second event unless the finger lifted very fast. index.html
  ignores mouse pointerdowns within 1 s of a touch.

- Echo Studio as bluetooth_speaker (2026-10-01): pairs, but refuses audio
  from the tablet. btmon: AVDTP Discover/SetConfiguration(SBC 48k)/Open all
  accepted, then the Echo sends AVDTP Close within ~30 ms and the link drops
  ~3 s later. Right after pairing the Echo had streamed TO the tablet
  (bluez_input), i.e. it took "Living Room" (CoD loudspeaker, A2DP Sink in
  SDP) as its own output speaker - what pairing from the Alexa app's "pair
  new device" does. Advertising CoD laptop at connect time (btmgmt class 1
  12) changed nothing, so it is remembered on the Echo: forget "Living Room"
  in the Alexa app, re-pair with "Alexa, pair" (untested whether the Echo
  then accepts a source that also has an A2DP Sink record). Device.Connect()
  also brought up the Echo->tablet direction, after which ours failed with
  EBUSY; the agent now uses ConnectProfile(A2DP Sink), counts the speaker as
  connected only when an A2DP transport in our source role exists 4 s later,
  otherwise disconnects and backs off 30 s doubling to 10 min (status in
  /run/livingroom-speaker.json for the panel). The old 30 s retry loop during
  an AirPlay session flapped WirePlumber's bluez node ("Object activation
  aborted: proxy destroyed") and the iPhone's AirPlay session dropped.
  Re-pairing with "Alexa, pair" fixed it: the Echo Studio accepts audio now.
  It has no AVRCP absolute volume (no MediaTransport1.Volume), so PipeWire
  uses software volume, and WirePlumber starts every new device route at
  device.routes.default-sink-volume = 0.4^3 (6.4 %, -24 dB): AirPlay to the
  Echo was very quiet. 51-livingroom-audio.conf sets it to 1.0; the iPhone
  and the speaker's own buttons set the loudness.

- Kiosk login at boot (2026-10-28): with AutomaticLogin, every boot GDM
  started the kiosk on tty2 while plymouth still held tty1; ~10 s later the
  boot finished (plymouth-quit-wait, multi-user.target), GDM started a
  greeter on tty1, sway lost the CRTC ("connector DSI-1: Failed to disable
  CRTC 60") and the session died; the TimedLogin fallback brought a second
  kiosk ~30 s later. Not reproducible with `systemctl restart gdm` (no
  plymouth). Fix: TimedLogin only (greeter first, kiosk after 10 s).
- Log out (dashboard picker, tap twice): `swaymsg exit`. logind keeps a
  closed session's processes (KillUserProcesses=no), so the receivers and
  livingroom-power ran on into the next session (keyboard light forced off in
  GNOME); livingroom-session now runs `loginctl terminate-session` after
  sway. After logout the greeter needs ~25 s to start on this Atom, then the
  10 s timed login returns to the kiosk unless an account is picked.
- Keyboard light: livingroom-power saves the level before turning it off
  (~livingroom/.config/livingroom/keyboard-light) and writes it back on
  SIGTERM/SIGHUP, straight to sysfs (73-livingroom-kbd-light.rules: group
  video) because a closing session's logind SetBrightness may be refused.
  GDM 50 has no PostSession scripts any more.
- Power key: kiosk -> logind HandlePowerKey=poweroff (clean shutdown, seen
  2026-10-11). GNOME had power-button-action 'suspend' (user setting; the
  chassis is "convertible", so GNOME's "tablets always suspend" rule does
  not apply) and the battery ran flat in s2idle; tablet/install.sh sets
  'interactive' (Power Off dialog, shuts down by itself after 60 s).
- Lid: logind/yogabook-modes-handler saw exactly one lid event since the
  kiosk exists (2026-10-11, in GNOME, suspended fine); nothing in the kiosk
  inhibits handle-lid-switch and logind is not "docked". Tested in the kiosk
  2026-10-28: "Lid closed" -> s2idle within 1 s, lid open wakes it and the
  modes handler re-enables the touchscreen. No change was needed.
