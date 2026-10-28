#!/usr/bin/python3
# Living-room display for the Yoga Book: a full-screen WebKit page (clock,
# weather, animated scene, "now playing") fed from here with
#  - the audio level of whatever plays on the default PipeWire sink
#    (Bluetooth A2DP, AirPlay audio, DLNA), via pw-record on the sink monitor
#  - "now playing" metadata (Bluetooth AVRCP via BlueZ, AirPlay via UxPlay's
#    metadata file)
#  - weather from Open-Meteo (no API key)
import json
import os
import subprocess
import threading
import time
import urllib.parse
import urllib.request

import gi
import numpy as np

gi.require_version("Gtk", "4.0")
gi.require_version("WebKit", "6.0")
from gi.repository import GLib, Gtk, WebKit  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
CONF = "/etc/livingroom.conf"
AIRPLAY_META = "/run/user/%d/uxplay-metadata.txt" % os.getuid()
AIRPLAY_COVER = "/run/user/%d/uxplay-cover.jpg" % os.getuid()
DLNA_PORT = 49494          # gmediarender -p (see livingroom-kiosk)

RATE = 8000             # level only: a low rate is plenty and costs nothing
HOP = 800               # 10 level updates/s
STATE = os.path.expanduser("~/.config/livingroom/state.json")
# Screen sleep settings from the Screen panel (read by livingroom-power) and
# what livingroom-power reports back.
POWER = os.path.expanduser("~/.config/livingroom/power.json")
POWER_STATUS = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "livingroom-power.json")
# Bluetooth speaker from the Speaker panel (read by livingroom-bt-agent,
# which connects it while cast audio plays)
SPEAKER = os.path.expanduser("~/.config/livingroom/speaker.json")
SPEAKER_STATUS = "/run/livingroom-speaker.json"     # written by livingroom-bt-agent
SCENES = ("autumn", "snow", "sakura", "fireflies", "rain", "mountains")
MY_PICTURES = os.path.expanduser("~/Pictures/Living Room")   # <scene>/*.jpg of your own


def log(msg):
    print(f"livingroom: {msg}", flush=True)


def load_conf():
    conf = {"city": "", "lat": None, "lon": None, "units": "celsius", "clock24": True,
            "theme": "auto", "weather": "card"}
    try:
        with open(CONF) as f:
            for line in f:
                line = line.split("#", 1)[0].strip()
                if "=" in line:
                    k, v = (x.strip() for x in line.split("=", 1))
                    conf[k] = v
    except OSError:
        pass
    conf["clock24"] = str(conf["clock24"]).lower() not in ("0", "no", "false")
    try:   # the scene picked on the screen wins over the config file
        with open(STATE) as f:
            st = json.load(f)
            conf["theme"] = st.get("theme", conf["theme"])
            conf["weather"] = st.get("weather", conf["weather"])
    except (OSError, ValueError):
        pass
    return conf


def scene_images():
    """Paintings per scene: the bundled ones (with credits) plus the user's own."""
    credits = {}
    try:
        with open(os.path.join(HERE, "scenes", "CREDITS.json")) as f:
            credits = {c["file"]: c for c in json.load(f)}
    except (OSError, ValueError):
        pass
    out = {}
    for scene in SCENES:
        imgs = []
        for base in (os.path.join(HERE, "scenes"), MY_PICTURES):
            d = os.path.join(base, scene)
            os.makedirs(d, exist_ok=True) if base == MY_PICTURES else None
            try:
                names = sorted(os.listdir(d))
            except OSError:
                continue
            for n in names:
                if n.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
                    c = credits.get(f"{scene}/{n}", {}) if base != MY_PICTURES else {}
                    imgs.append({"url": "file://" + urllib.parse.quote(os.path.join(d, n)),
                                 "title": c.get("title", ""), "artist": c.get("artist", ""),
                                 "date": c.get("date", "")})
        mine = [i for i in imgs if not i["artist"]]
        out[scene] = mine or imgs      # your own pictures replace the bundled ones
    return out


def write_json(path, data):
    """Survives a crash or power cut: on disk before it replaces the old file."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w") as f:
        json.dump(data, f, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(path + ".tmp", path)
    dfd = os.open(os.path.dirname(path), os.O_RDONLY)
    os.fsync(dfd)
    os.close(dfd)


def save_state(**kw):
    state = {}
    try:
        with open(STATE) as f:
            state = json.load(f)
    except (OSError, ValueError):
        pass
    state.update(kw)
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, "w") as f:
        json.dump(state, f)


class Level(threading.Thread):
    """RMS level (0..1) of the default sink's monitor, 10 times a second."""

    def __init__(self, cb):
        super().__init__(daemon=True)
        self.cb = cb

    def run(self):
        while True:
            try:
                self.capture()
            except Exception as e:  # keep the display alive whatever happens
                log(f"level: {e}")
            time.sleep(2)

    def capture(self):
        p = subprocess.Popen(
            ["pw-record", "-P", "{ stream.capture.sink=true node.name=livingroom-level }",
             "--rate", str(RATE), "--channels", "1", "--format", "s16", "-"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        quiet = 0
        try:
            while True:
                raw = p.stdout.read(HOP * 2)
                if len(raw) < HOP * 2:
                    return
                x = np.frombuffer(raw, np.int16).astype(np.float32) / 32768
                rms = float(np.sqrt(np.mean(x * x)))
                # silence: once a second is enough for the page
                quiet = quiet + 1 if rms < 1e-4 else 0
                if quiet > 10 and quiet % 10:
                    continue
                self.cb(round(rms, 4))
        finally:
            p.kill()


class NowPlaying(threading.Thread):
    """Track info from Bluetooth (BlueZ MediaPlayer1) or AirPlay (UxPlay)."""

    def __init__(self, cb):
        super().__init__(daemon=True)
        self.cb = cb
        self.last = None

    def bluetooth(self):
        try:
            import dbus
            bus = dbus.SystemBus()
            om = dbus.Interface(bus.get_object("org.bluez", "/"),
                                "org.freedesktop.DBus.ObjectManager")
            for path, ifaces in om.GetManagedObjects().items():
                mp = ifaces.get("org.bluez.MediaPlayer1")
                if mp and mp.get("Status") == "playing":
                    t = mp.get("Track", {})
                    dev = ifaces.get("org.bluez.MediaPlayer1", {}).get("Device", "")
                    name = ""
                    if dev:
                        d = om.GetManagedObjects().get(dev, {}).get("org.bluez.Device1", {})
                        name = str(d.get("Alias", ""))
                    return {"title": str(t.get("Title", "")), "artist": str(t.get("Artist", "")),
                            "album": str(t.get("Album", "")), "source": f"Bluetooth · {name}".strip(" ·")}
        except Exception:
            pass
        return None

    def airplay(self):
        try:
            if time.time() - os.path.getmtime(AIRPLAY_META) > 600:
                return None
            info = {}
            with open(AIRPLAY_META) as f:
                for line in f:
                    if ":" in line:
                        k, v = line.split(":", 1)
                        info[k.strip().lower()] = v.strip()
            if info.get("title"):
                cover = ""
                try:
                    if abs(os.path.getmtime(AIRPLAY_COVER) - os.path.getmtime(AIRPLAY_META)) < 30:
                        cover = "file://%s?%d" % (AIRPLAY_COVER, os.path.getmtime(AIRPLAY_COVER))
                except OSError:
                    pass
                return {"title": info.get("title", ""), "artist": info.get("artist", ""),
                        "album": info.get("album", ""), "source": "AirPlay", "cover": cover}
        except OSError:
            pass
        return None

    def dlna(self):
        """Title/artist/art the sender passed to gmediarender (DIDL-Lite metadata)."""
        import html
        import re
        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("192.0.2.1", 9))          # no traffic: just picks the LAN address
            base = f"http://{s.getsockname()[0]}:{DLNA_PORT}"
            s.close()
            if not hasattr(self, "_dlna_ctl"):
                d = urllib.request.urlopen(base + "/description.xml", timeout=2).read().decode()
                self._dlna_ctl = re.search(r"AVTransport.*?<controlURL>(.*?)</controlURL>", d, re.S).group(1)

            def soap(action):
                body = ('<?xml version="1.0"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">'
                        f'<s:Body><u:{action} xmlns:u="urn:schemas-upnp-org:service:AVTransport:1">'
                        f'<InstanceID>0</InstanceID></u:{action}></s:Body></s:Envelope>')
                req = urllib.request.Request(base + self._dlna_ctl, body.encode(), {
                    "Content-Type": 'text/xml; charset="utf-8"',
                    "SOAPACTION": f'"urn:schemas-upnp-org:service:AVTransport:1#{action}"'})
                return urllib.request.urlopen(req, timeout=2).read().decode()

            if "<CurrentTransportState>PLAYING<" not in soap("GetTransportInfo"):
                return None
            meta = html.unescape(re.search(r"<CurrentURIMetaData>(.*?)</CurrentURIMetaData>",
                                           soap("GetMediaInfo"), re.S).group(1))
            tag = lambda t: html.unescape((re.search(rf"<{t}[^>]*>(.*?)</{t}>", meta, re.S) or [None, ""])[1]).strip()
            return {"title": tag("dc:title"), "artist": tag("upnp:artist") or tag("dc:creator"),
                    "album": tag("upnp:album"), "source": "Cast", "cover": tag("upnp:albumArtURI")}
        except Exception:
            return None

    def run(self):
        while True:
            now = self.bluetooth() or self.airplay() or self.dlna()
            if now != self.last:
                self.last = now
                self.cb(now)
            time.sleep(2)


class Speakers:
    """Speaker panel: finds, pairs and forgets Bluetooth speakers (BlueZ
    allows this user), and saves the choice for livingroom-bt-agent. Calls
    block, so they run on worker threads; the result goes to cb."""

    A2DP_SINK = "0000110b-0000-1000-8000-00805f9b34fb"
    SCAN = 40          # s

    def __init__(self, conf, cb):
        self.conf, self.cb = conf, cb
        self.scan_until = 0
        self.busy = ""             # "Pairing <name>…"
        self.error = ""

    @staticmethod
    def bus():
        import dbus
        return dbus.SystemBus(private=True)

    def setting(self):
        try:
            with open(SPEAKER) as f:
                p = json.load(f)
            return {"address": p.get("address", ""), "name": p.get("name", ""),
                    "enabled": bool(p.get("enabled", True)), "source": "panel"}
        except (OSError, ValueError):
            on = str(self.conf.get("bluetooth_speaker_enabled", "yes")).lower() not in ("no", "off", "false", "0")
            return {"address": self.conf.get("bluetooth_speaker", ""), "name": "",
                    "enabled": on, "source": "conf"}

    def save(self, **kw):
        s = self.setting()
        s.update(kw)
        s.pop("source", None)
        write_json(SPEAKER, s)
        log(f"speaker -> {s}")

    def status(self):
        import dbus
        st = self.setting()
        st.update(scanning=time.time() < self.scan_until, busy=self.busy, error=self.error,
                  paired=False, connected=False, found=[], agent=None)
        try:
            with open(SPEAKER_STATUS) as f:
                a = json.load(f)
            if a.get("speaker", "").lower() == st["address"].lower():
                st["agent"] = a
        except (OSError, ValueError):
            pass
        try:
            bus = self.bus()
            objs = dbus.Interface(bus.get_object("org.bluez", "/"),
                                  "org.freedesktop.DBus.ObjectManager").GetManagedObjects()
            bus.close()
        except dbus.DBusException:
            return st
        want = st["address"].lower()
        for path, ifaces in objs.items():
            d = ifaces.get("org.bluez.Device1")
            if not d:
                continue
            addr, alias = str(d.get("Address", "")), str(d.get("Alias", ""))
            if want and want in (addr.lower(), alias.lower(), str(d.get("Name", "")).lower()):
                st.update(paired=bool(d.get("Paired")), connected=bool(d.get("Connected")))
                st["name"] = st["name"] or alias
                continue
            major = (int(d.get("Class", 0)) >> 8) & 0x1f
            sink = self.A2DP_SINK in [str(u).lower() for u in d.get("UUIDs", [])]
            # speakers/headphones, seen in this scan or paired before
            if (major == 0x04 or (sink and major != 0x02)) and ("RSSI" in d or d.get("Paired")):
                st["found"].append({"address": addr, "name": alias, "paired": bool(d.get("Paired")),
                                    "rssi": int(d.get("RSSI", -999))})
        st["found"].sort(key=lambda x: -x["rssi"])
        return st

    def push(self):
        self.cb(self.status())

    def run(self, fn, *a):
        def go():
            try:
                fn(*a)
            except Exception as e:
                self.error = getattr(e, "get_dbus_message", lambda: str(e))() or str(e)
                log(f"speaker: {self.error}")
            self.busy = ""
            self.push()
        threading.Thread(target=go, daemon=True).start()

    def scan(self):
        def go():
            import dbus
            bus = self.bus()
            a = dbus.Interface(bus.get_object("org.bluez", "/org/bluez/hci0"), "org.bluez.Adapter1")
            a.SetDiscoveryFilter({"Transport": "bredr"})
            a.StartDiscovery()          # ends when this connection closes
            self.scan_until = time.time() + self.SCAN
            try:
                while time.time() < self.scan_until:
                    self.push()
                    time.sleep(2)
            finally:
                self.scan_until = 0
                try:
                    a.StopDiscovery()
                except dbus.DBusException:
                    pass
                bus.close()
        if time.time() >= self.scan_until:
            self.error = ""
            self.run(go)

    def use(self, addr, name):
        def go():
            import dbus
            self.scan_until = 0              # pairing goes faster without inquiry
            bus = self.bus()
            path = "/org/bluez/hci0/dev_" + addr.replace(":", "_").upper()
            props = dbus.Interface(bus.get_object("org.bluez", path), "org.freedesktop.DBus.Properties")
            if not props.Get("org.bluez.Device1", "Paired"):
                self.busy = f"Pairing {name}…"
                self.push()
                dbus.Interface(bus.get_object("org.bluez", path), "org.bluez.Device1").Pair(timeout=60)
            props.Set("org.bluez.Device1", "Trusted", True)
            bus.close()
            self.save(address=addr, name=name, enabled=True)
        self.error = ""
        self.run(go)

    def remove(self):
        def go():
            import dbus
            st = self.status()
            if st["paired"] and st["address"]:
                bus = self.bus()
                path = "/org/bluez/hci0/dev_" + st["address"].replace(":", "_").upper()
                try:
                    dbus.Interface(bus.get_object("org.bluez", "/org/bluez/hci0"),
                                   "org.bluez.Adapter1").RemoveDevice(path)
                except dbus.DBusException:
                    pass                     # a name from the config file, not an address
                bus.close()
            self.save(address="", name="")
        self.error = ""
        self.run(go)

    def enable(self, on):
        self.save(enabled=bool(on))
        self.push()


class Weather(threading.Thread):
    def __init__(self, conf, cb):
        super().__init__(daemon=True)
        self.conf, self.cb = conf, cb

    def locate(self):
        c = self.conf
        if c.get("lat") and c.get("lon"):
            return float(c["lat"]), float(c["lon"]), c.get("city") or ""
        if c.get("city"):
            q = urllib.parse.quote(c["city"])
            r = self.get(f"https://geocoding-api.open-meteo.com/v1/search?name={q}&count=1")
            g = r["results"][0]
            return g["latitude"], g["longitude"], g["name"]
        r = self.get("http://ip-api.com/json/?fields=lat,lon,city")
        return r["lat"], r["lon"], r.get("city", "")

    @staticmethod
    def get(url):
        with urllib.request.urlopen(url, timeout=20) as r:
            return json.load(r)

    def run(self):
        loc = None
        while True:
            try:
                if loc is None:
                    loc = self.locate()
                lat, lon, city = loc
                unit = "fahrenheit" if self.conf.get("units") == "fahrenheit" else "celsius"
                w = self.get(
                    "https://api.open-meteo.com/v1/forecast"
                    f"?latitude={lat}&longitude={lon}&timezone=auto&temperature_unit={unit}"
                    "&current=temperature_2m,apparent_temperature,relative_humidity_2m,"
                    "weather_code,is_day,wind_speed_10m"
                    "&hourly=temperature_2m,weather_code,is_day,precipitation_probability"
                    "&daily=weather_code,temperature_2m_max,temperature_2m_min,sunrise,sunset"
                    "&forecast_days=5")
                w["city"] = city
                self.cb(w)
                time.sleep(900)
            except Exception as e:
                log(f"weather: {e}")
                time.sleep(120)


class App(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="local.livingroom")
        self.conf = load_conf()
        log(f"config: {self.conf}")
        self.ready = False
        self.pending = {}

    def do_activate(self):
        # Without portals GTK derives the DPI from the panel's physical size
        # (1920 px / 216 mm = 226 dpi), which WebKit turns into a 2.35x page
        # zoom. The page sizes itself in vh/vw, so pin the standard 96 dpi.
        Gtk.Settings.get_default().set_property("gtk-xft-dpi", 96 * 1024)
        win = Gtk.ApplicationWindow(application=self)
        self.view = WebKit.WebView()
        ucm = self.view.get_user_content_manager()
        ucm.register_script_message_handler("lr", None)
        ucm.connect("script-message-received::lr", self.on_message)
        s = self.view.get_settings()
        s.set_allow_file_access_from_file_urls(True)
        s.set_hardware_acceleration_policy(WebKit.HardwareAccelerationPolicy.ALWAYS)
        s.set_enable_developer_extras(False)
        self.view.connect("load-changed", self.on_load)
        win.set_child(self.view)
        # No win.fullscreen(): the kiosk compositor makes every window full screen.
        win.present()
        # hide the pointer: nothing to click on
        win.set_cursor_from_name("none")
        self.view.load_uri("file://" + os.path.join(HERE, "index.html"))
        Level(lambda rms: self.push("level", rms)).start()
        NowPlaying(lambda np_: self.push("nowplaying", np_)).start()
        Weather(self.conf, lambda w: self.push("weather", w)).start()
        self.speakers = Speakers(self.conf, lambda st: self.push("speaker", st))

    def on_load(self, view, event):
        if event == WebKit.LoadEvent.FINISHED:
            self.ready = True
            self.push("config", {"clock24": self.conf["clock24"], "theme": self.conf["theme"],
                                 "weather": self.conf["weather"],
                                 "scenes": scene_images()})
            for k, v in list(self.pending.items()):
                self.push(k, v)

    def on_message(self, manager, value):
        try:
            msg = json.loads(value.to_string())
            if "tap" in msg:
                log(f"tap {msg['tap']}")
            if "theme" in msg:
                self.conf["theme"] = msg["theme"]
                save_state(theme=msg["theme"])
                log(f"theme -> {msg['theme']}")
            if "power_get" in msg:
                self.push_power()
            if "power_set" in msg:
                p = msg["power_set"]
                clean = {"screen": p["screen"], "sleep_after": float(p["sleep_after"]),
                         "wake_on": list(p["wake_on"]), "schedules": list(p["schedules"]),
                         "brightness": p.get("brightness", "auto"),
                         "keyboard_light": p.get("keyboard_light", "off")}
                write_json(POWER, clean)
                log(f"screen power -> {clean}")
                # livingroom-power applies it within a second
                GLib.timeout_add(1500, lambda: self.push_power() and False)
            if "speaker_get" in msg:
                self.speakers.run(lambda: None)
            if "speaker_scan" in msg:
                self.speakers.scan()
            if "speaker_use" in msg:
                self.speakers.use(msg["speaker_use"]["address"], msg["speaker_use"]["name"])
            if "speaker_remove" in msg:
                self.speakers.remove()
            if "speaker_enable" in msg:
                self.speakers.enable(msg["speaker_enable"])
            if "logout" in msg:
                # ends the sway session; GDM shows the login screen (and its
                # timed login brings the kiosk back unless an account is picked)
                log("log out")
                subprocess.Popen(["swaymsg", "exit"])
            if "weather" in msg:
                self.conf["weather"] = msg["weather"]
                save_state(weather=msg["weather"])
                log(f"weather card -> {msg['weather']}")
        except Exception as e:
            log(f"message: {e}")

    def push_power(self):
        try:
            with open(POWER_STATUS) as f:
                self.push("power", json.load(f))
        except (OSError, ValueError):
            self.push("power", None)      # livingroom-power not running

    def push(self, kind, data):
        # called from worker threads: hop to the GTK main loop
        GLib.idle_add(self._push, kind, data)

    def _push(self, kind, data):
        if not self.ready:
            self.pending[kind] = data
            return False
        js = f"window.lr && window.lr({json.dumps(kind)}, {json.dumps(data)});"
        self.view.evaluate_javascript(js, -1, None, None, None, None, None)
        return False


if __name__ == "__main__":
    App().run(None)
