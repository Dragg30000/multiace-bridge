# /// script
# requires-python = ">=3.12"
#
# [tool.orcaslicer.plugin]
# name = "multiACE Bridge (Snapmaker U1)"
# description = "Interface pour multiACE de decay71 (Snapmaker U1) dans OrcaSlicer : panneau ACE, interface web multiACE en onglet, et envoi de l'export au Preflight de multiACE."
# author = "Dragg avec son ami Claude"
# version = "0.34.3"
# ///
"""multiACE Bridge - relie OrcaSlicer 2.5 a multiACE (decay71/multiACE) sur une Snapmaker U1.

Capacites :

* Onglet "multiACE" : l'interface web de multiACE (http://<U1>/multiace/) dans OrcaSlicer.
* Panneau ACE ancre : tetes, bobines, poids, sechage, ecran de la U1 ; charger / echanger /
  decharger / secher / calibrer dans une file d'attente ; homing automatique en option ;
  edition des slots et association des bobines de la table multiACE (slots sans RFID).
* Pipeline "multiACE : envoyer au Preflight" : a l'export, le plugin execute le Preflight fourni par
  la U1 (code multiACE de sa version, /api/preflight/pysrc + livedata), sans logique propre, verifie
  tout puis imprime. Si une verification echoue, le G-code original part dans le Preflight de
  multiACE (/api/preflight/inbox).
* Script "multiACE : renvoyer le dernier G-code".

Plugin communautaire, non officiel, sans lien avec Snapmaker ou OrcaSlicer. multiACE est le
projet de decay71 (github.com/decay71/multiACE) : ce plugin n'en est qu'une interface dans Orca.
Licence GPL-3.0, comme multiACE.
"""

import json
import os
import re
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

import orca

VERSION = "0.34.3"
TIMEOUT_UI = 4          # secondes, appels faits sur le fil de l'interface
TIMEOUT_BG = 8          # secondes, appels en arriere-plan

# Arret du plugin (desinstallation, desactivation, fermeture d'OrcaSlicer) : OrcaSlicer appelle on_unload
# sur chaque capacite ; tous les fils de fond s'arretent alors (plus aucun appel reseau ensuite).
_STOP = threading.Event()


def plugin_shutdown():
    _STOP.set()
UPLOAD_TIMEOUT = 300    # secondes, envoi d'un gros G-code
BUNDLE_ID = "multiace-bridge"
NOZZLES = ("0.2", "0.4", "0.6", "0.8")
NOZZLE_CHOICES = ("Standard", "Haut débit")   # buses reelles possibles d'une tete de la U1
NOZZLE_BLOCK_G = 5      # g : un filament plus lourd sur le mauvais type de buse bloque l'envoi (sauf confirmation)
PROCESSED_MARKERS = ("; multiACE processed:", "; multiACE auto-load:")
U1CONTROL_MARKER = "; u1control:"

# Pas de proxy systeme : l'imprimante est sur le reseau local.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


# --------------------------------------------------------------------------- stockage

_storage_cache = None


def storage_dir():
    global _storage_cache
    if _storage_cache is None:
        path = orca.host.plugin.storage()
        if not path:
            raise RuntimeError("dossier de stockage du plugin indisponible")
        os.makedirs(path, exist_ok=True)
        _storage_cache = path
    return _storage_cache


def _settings_path():
    """Reglages hors du dossier du plugin : ils survivent a une desinstallation / reinstallation."""
    root = storage_dir()
    parts = root.replace("\\", "/").split("/")
    if "orca_plugins" in parts:
        stable_dir = os.path.join("/".join(parts[: parts.index("orca_plugins")]) or "/", "multiace_bridge")
        stable = os.path.join(stable_dir, "settings.json")
        old = os.path.join(root, "settings.json")
        if not os.path.exists(stable) and os.path.exists(old):
            try:
                os.makedirs(stable_dir, exist_ok=True)
                with open(old, "rb") as src, open(stable, "wb") as dst:
                    dst.write(src.read())
            except OSError:
                return old
        return stable
    return os.path.join(root, "settings.json")


def load_settings():
    data = {}
    try:
        with open(_settings_path(), "r", encoding="utf-8") as f:
            loaded = json.load(f)
        if isinstance(loaded, dict):
            data = loaded
    except (OSError, ValueError):
        pass
    host = data.get("host") if isinstance(data.get("host"), str) else ""
    nozzle = data.get("nozzle") if data.get("nozzle") in NOZZLES else "0.4"
    auto_panel = data.get("auto_panel") if isinstance(data.get("auto_panel"), bool) else True
    auto_pipeline = data.get("auto_pipeline") if isinstance(data.get("auto_pipeline"), bool) else True
    popup = data.get("popup") if isinstance(data.get("popup"), bool) else True
    screen = data.get("screen") if data.get("screen") in ("off", "top", "bottom") else "off"
    camera = data.get("camera") if data.get("camera") in ("off", "top", "bottom") else "off"
    compact = data.get("compact") if isinstance(data.get("compact"), bool) else False
    prep_pos = data.get("prep_pos") if data.get("prep_pos") in ("top", "bottom") else "top"
    raw_folds = data.get("folds") if isinstance(data.get("folds"), dict) else {}
    folds = {k: v for k, v in list(raw_folds.items())[:12]
             if isinstance(k, str) and re.fullmatch(r"heads|prep|ace[0-7]", k) and isinstance(v, bool)}
    auto_home = data.get("auto_home") if isinstance(data.get("auto_home"), bool) else False
    ace_guard = data.get("ace_guard") if isinstance(data.get("ace_guard"), bool) else True
    u1_code = data.get("u1_code") if isinstance(data.get("u1_code"), bool) else True
    real = data.get("real_nozzles") if isinstance(data.get("real_nozzles"), list) else []
    real_nozzles = [(real[h] if h < len(real) and real[h] in NOZZLE_CHOICES else "") for h in range(4)]
    profile_base = data.get("profile_base") if isinstance(data.get("profile_base"), str) else ""
    filaments = [x for x in data.get("filaments") or [] if isinstance(x, str)][:16]
    return {"host": host, "nozzle": nozzle, "auto_panel": auto_panel, "popup": popup,
            "screen": screen, "camera": camera, "compact": compact, "prep_pos": prep_pos, "folds": folds,
            "profile_base": profile_base, "filaments": filaments, "auto_pipeline": auto_pipeline,
            "auto_home": auto_home, "ace_guard": ace_guard, "u1_code": u1_code,
            "real_nozzles": real_nozzles}


def save_settings(settings):
    write_json_atomic(_settings_path(), settings)


def write_json_atomic(path, value):
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", suffix=".json", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(value, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def last_gcode_paths():
    root = storage_dir()
    return os.path.join(root, "last.gcode"), os.path.join(root, "last.json")


def last_gcode_info():
    _, meta_path = last_gcode_paths()
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        return meta if isinstance(meta, dict) else None
    except (OSError, ValueError):
        return None


def keep_last_gcode(source, name):
    """Garde une copie de l'export original pour pouvoir le renvoyer (l'inbox est a usage unique)."""
    gcode_path, meta_path = last_gcode_paths()
    tmp = gcode_path + ".tmp"
    with open(source, "rb") as src, open(tmp, "wb") as dst:
        while True:
            chunk = src.read(1 << 20)
            if not chunk:
                break
            dst.write(chunk)
    os.replace(tmp, gcode_path)
    write_json_atomic(meta_path, {"name": name, "size": os.path.getsize(gcode_path), "ts": time.time()})


# --------------------------------------------------------------------------- adresse

def normalize_host(text):
    """'192.168.1.50', 'http://u1.local/multiace', 'u1.local:80' -> 'hote[:port]' ou ''."""
    text = (text or "").strip().strip('"')
    if not text:
        return ""
    if "://" not in text:
        text = "http://" + text
    if re.search(r"[\x00-\x20\x7f]", text):
        return ""
    try:
        parts = urllib.parse.urlsplit(text)
        host = parts.hostname or ""
        port = parts.port
    except ValueError:          # port illisible, crochets mal formes...
        return ""
    if not host or not re.fullmatch(r"[A-Za-z0-9.\-]+|\[[0-9A-Fa-f:]+\]|[0-9A-Fa-f:]+", host):
        return ""
    if ":" in host and not host.startswith("["):
        host = "[" + host + "]"
    return host + (":%d" % port if port and port != 80 else "")


def origin_of(host):
    return "http://" + host if host else ""


def error_message(body):
    """Extrait le message utile d'une reponse d'erreur multiACE / Moonraker (sans la trace Python)."""
    for _ in range(3):
        try:
            parsed = json.loads(body) if isinstance(body, str) else body
        except ValueError:
            break
        if isinstance(parsed, dict):
            inner = parsed.get("detail", parsed.get("error", parsed.get("message")))
            if isinstance(inner, dict):
                inner = inner.get("message") or inner.get("error") or inner
            if inner is None:
                break
            body = inner
            continue
        break
    text = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)
    m = re.search(r'"message"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
    if m:
        text = m.group(1)
    return text.split("\n")[0].split("Traceback")[0].strip()[:300]


def gcode_safe(value, limit=40):
    """Valeur libre (marque, type, matiere) envoyee dans une commande G-code via multiACE : sans les
    caracteres qui coupent ou prolongent la ligne Klipper (# * ; " ' retour a la ligne, controle)."""
    v = re.sub(r"[#*;\"'\\]", "", str(value or ""))
    v = re.sub(r"[\x00-\x1f\x7f]", " ", v)
    return " ".join(v.split())[:limit]


def needs_home(text):
    return bool(re.search(r"must home|home .*first|not homed|0003-0522", text or "", re.I))


def friendly_error(text):
    t = text or ""
    if needs_home(t):
        return ("la U1 n'est pas référencée (l'écran affiche « Axis Movement Anomaly ») : il faut un homing "
                "avant de bouger les têtes.")
    if re.search(r"printer is not ready|klippy.*(shutdown|not ready)", t, re.I):
        return "Klipper n'est pas prêt sur la U1 (redémarrage ou erreur en cours) : attends puis réessaie."
    if re.search(r"timed out|timeout", t, re.I):
        return "la U1 n'a pas répondu à temps."
    return t


def preset_host():
    """Adresse du profil imprimante selectionne (print_host), si c'est une U1."""
    try:
        bundle = orca.host.preset_bundle()
        preset = bundle.current_printer_preset()
        text = (preset.config_value("print_host") or bundle.full_config_value("print_host") or "")
        return normalize_host(text)
    except Exception:
        return ""


def effective_host(explicit=""):
    host = normalize_host(explicit) or load_settings()["host"]
    if host:
        return host
    host = preset_host()
    if host:
        # Memorise l'adresse : au prochain lancement, l'autorisation reseau est demandee d'un coup au chargement.
        try:
            st = load_settings()
            st["host"] = host
            save_settings(st)
        except Exception:
            pass
    return host


# --------------------------------------------------------------------------- client HTTP

class MultiAceError(Exception):
    pass


class MultiAce:
    def __init__(self, host):
        if not host:
            raise MultiAceError("Adresse de la U1 non renseignee : entre son IP dans le panneau ACE (Options → Adresse de la U1).")
        self.host = host
        self.base = origin_of(host) + "/multiace/api"

    def _open(self, method, path, data=None, headers=None, timeout=TIMEOUT_BG):
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers or {})
        try:
            return _OPENER.open(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = error_message(e.read(65536).decode("utf-8", "replace"))
            except Exception:
                pass
            err = MultiAceError("HTTP %d%s" % (e.code, (" : " + detail) if detail else ""))
            err.status = e.code
            raise err
        except PermissionError:
            raise
        except (urllib.error.URLError, OSError) as e:
            reason = getattr(e, "reason", e)
            # urllib enveloppe le refus du controle d'acces d'OrcaSlicer dans une URLError.
            if isinstance(reason, PermissionError):
                raise reason
            raise MultiAceError("U1 injoignable a %s (%s)" % (self.host, reason))

    def get_json(self, path, timeout=TIMEOUT_BG):
        with self._open("GET", path, timeout=timeout) as resp:
            raw = resp.read()
        try:
            return json.loads(raw.decode("utf-8"))
        except ValueError:
            raise MultiAceError("reponse illisible de %s (multiACE est-il installe ?)" % path)

    def state(self, timeout=TIMEOUT_BG):
        return self.get_json("/state", timeout)

    def inbox(self, timeout=TIMEOUT_BG):
        return self.get_json("/preflight/inbox", timeout)

    def discard_inbox(self, timeout=TIMEOUT_BG):
        with self._open("DELETE", "/preflight/inbox", timeout=timeout) as resp:
            resp.read()

    def macro(self, name, args, timeout=900):
        """Lance une macro multiACE via son API (meme chemin que l'interface web). Bloque jusqu'a la fin."""
        body = json.dumps({"name": name, "args": args}).encode("utf-8")
        with self._open("POST", "/macro", data=body, headers={"Content-Type": "application/json"}, timeout=timeout) as resp:
            resp.read()

    def home(self, timeout=180):
        """Homing (G28) par l'API multiACE (/macro accepte toute commande G-code) : meme adresse que le
        reste, donc deja autorisee par OrcaSlicer (le port 7125 de Moonraker ne l'est pas)."""
        try:
            self.macro("G28", {}, timeout=timeout)
        except MultiAceError as e:
            raise MultiAceError("homing refusé : %s" % friendly_error(str(e)))

    def homed_axes(self, timeout=TIMEOUT_UI):
        """Axes references par Klipper ("xyz" si tout est bon). None si Moonraker ne repond pas."""
        url = origin_of(self.host) + "/printer/objects/query?toolhead=homed_axes"   # Moonraker via nginx :80
        try:
            with _OPENER.open(url, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return str(data["result"]["status"]["toolhead"].get("homed_axes") or "")
        except Exception:
            return None

    def head_nozzle_types(self, timeout=TIMEOUT_UI):
        """Buses vissees sur les 4 tetes, lues dans la U1 (extruderN.nozzle_volume_type, firmware recent ;
        meme source que multiACE). Liste de 4 valeurs de NOZZLE_CHOICES, "" si la U1 ne le dit pas.
        Lecture seule."""
        names = ["extruder", "extruder1", "extruder2", "extruder3"]
        url = origin_of(self.host) + "/printer/objects/query?" + "&".join(names)   # Moonraker via nginx :80
        try:
            with _OPENER.open(url, timeout=timeout) as resp:
                status = json.loads(resp.read().decode("utf-8"))["result"]["status"]
        except Exception:
            return ["", "", "", ""]
        out = []
        for name in names:
            v = str((status.get(name) or {}).get("nozzle_volume_type") or "").strip().lower().replace(" ", "_")
            out.append({"standard": "Standard", "high_flow": "Haut débit"}.get(v, ""))
        return out

    def active_head(self, timeout=TIMEOUT_UI):
        """Tete qui imprime en ce moment (0-3) d'apres Klipper (toolhead.extruder), None si inconnue."""
        url = origin_of(self.host) + "/printer/objects/query?toolhead=extruder"   # Moonraker via nginx :80
        try:
            with _OPENER.open(url, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            name = str(data["result"]["status"]["toolhead"].get("extruder") or "")
        except Exception:
            return None
        m = re.fullmatch(r"extruder([0-3]?)", name)
        return int(m.group(1) or 0) if m else None

    def screen_tap(self, x, y, timeout=TIMEOUT_UI):
        """Extended Firmware : toucher l'ecran de la U1 (POST /screen/touch, hors /multiace)."""
        url = origin_of(self.host) + "/screen/touch?a=tap&x=%d&y=%d" % (x, y)
        req = urllib.request.Request(url, data=b"", method="POST")
        try:
            with _OPENER.open(req, timeout=timeout) as resp:
                resp.read()
        except urllib.error.URLError as e:
            if isinstance(getattr(e, "reason", None), PermissionError):
                raise e.reason
            raise MultiAceError("ecran distant injoignable (%s)" % getattr(e, "reason", e))

    def set_override(self, ace, slot, material, brand, subtype, color, timeout=TIMEOUT_BG):
        body = json.dumps({"ace": ace, "slot": slot, "material": material, "brand": brand,
                           "subtype": subtype, "color": color}).encode("utf-8")
        with self._open("POST", "/slot-override", data=body, headers={"Content-Type": "application/json"},
                        timeout=timeout) as resp:
            resp.read()

    def clear_override(self, ace, slot, timeout=TIMEOUT_BG):
        with self._open("DELETE", "/slot-override/%d/%d" % (ace, slot), timeout=timeout) as resp:
            resp.read()

    def upload_to_printer(self, path, name):
        """Televerse dans la liste des fichiers de la U1 (Moonraker, via nginx) sans lancer l'impression."""
        return self.send_gcode(path, name, endpoint="moonraker")

    def send_gcode(self, path, name, endpoint="/preflight/inbox"):
        """POST multipart en flux (les G-code multi-couleurs depassent souvent 100 Mo)."""
        name = os.path.basename(name or path)
        if not re.search(r"\.(gcode|gco|g)$", name, re.IGNORECASE):
            name += ".gcode"
        safe = re.sub(r"[\x00-\x1f\x7f\"\\/]", "_", name)[-180:]
        boundary = "----multiACEBridge" + uuid.uuid4().hex
        head = ("--%s\r\nContent-Disposition: form-data; name=\"file\"; filename=\"%s\"\r\n"
                "Content-Type: application/octet-stream\r\n\r\n" % (boundary, safe)).encode("utf-8")
        if endpoint == "moonraker":
            head = ("--%s\r\nContent-Disposition: form-data; name=\"root\"\r\n\r\ngcodes\r\n" % boundary).encode("ascii") + head
        tail = ("\r\n--%s--\r\n" % boundary).encode("ascii")
        size = os.path.getsize(path)

        def body():
            yield head
            with open(path, "rb") as f:
                while True:
                    chunk = f.read(1 << 20)
                    if not chunk:
                        break
                    yield chunk
            yield tail

        headers = {"Content-Type": "multipart/form-data; boundary=" + boundary,
                   "Content-Length": str(len(head) + size + len(tail))}
        if endpoint == "moonraker":
            url = origin_of(self.host) + "/server/files/upload"     # Moonraker via nginx :80 (deja autorise)
            req = urllib.request.Request(url, data=body(), method="POST", headers=headers)
            try:
                with _OPENER.open(req, timeout=UPLOAD_TIMEOUT) as resp:
                    raw = resp.read()
            except urllib.error.URLError as e:
                if isinstance(getattr(e, "reason", None), PermissionError):
                    raise e.reason
                raise MultiAceError("televersement vers la U1 impossible (%s)" % getattr(e, "reason", e))
        else:
            with self._open("POST", endpoint, data=body(), headers=headers, timeout=UPLOAD_TIMEOUT) as resp:
                raw = resp.read()
        try:
            return json.loads(raw.decode("utf-8"))
        except ValueError:
            return {"ok": True}


_probed = set()


def probe_network(host, force=False):
    """Premier contact SUR LE FIL DE L'INTERFACE : OrcaSlicer peut y afficher tout de suite sa demande
    d'autorisation reseau et memoriser la reponse (depuis un fil d'arriere-plan, il la refuse d'office)."""
    if not host or (host in _probed and not force):
        return
    _probed.add(host)
    try:
        MultiAce(host).get_json("/version", timeout=1.5)
    except Exception:
        pass



def permission_text(host):
    return ("OrcaSlicer a bloqué l'accès réseau vers %s. Clique « Autoriser et réessayer » et accepte la "
            "demande d'OrcaSlicer (une seule fois)." % (origin_of(host) or "la U1"))


# --------------------------------------------------------------------------- G-code

def read_head_tail(path, head_bytes=65536, tail_bytes=262144):
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        head = f.read(min(size, head_bytes)).decode("utf-8", "replace")
        tail = ""
        if size > head_bytes:
            f.seek(max(head_bytes, size - tail_bytes))
            tail = f.read().decode("utf-8", "replace")
    return head, tail


def gcode_facts(path):
    head, tail = read_head_tail(path)
    text = head + "\n" + tail
    processed = any(m in head for m in PROCESSED_MARKERS)
    u1control = U1CONTROL_MARKER in text
    used = None
    m = re.search(r"^;\s*filament used \[mm\]\s*=\s*(.+)$", text, re.MULTILINE)
    if m:
        values = []
        for part in re.split(r"[,;]", m.group(1)):
            try:
                values.append(float(part.strip()))
            except ValueError:
                pass
        used = sum(1 for v in values if v > 0)
    tools = sorted({int(t) for t in re.findall(r"^T(\d+)\s*$", tail, re.MULTILINE)})
    return {"processed": processed, "u1control": u1control, "filaments_used": used, "max_tool_seen": tools[-1] if tools else None}


# --------------------------------------------------------------------------- page

ICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#FEFEFE" stroke-width="1.6">
<rect x="2.5" y="5" width="19" height="14" rx="2.5"/>
<circle cx="7" cy="12" r="2.2"/><circle cx="12" cy="12" r="2.2"/><circle cx="17" cy="12" r="2.2"/>
<path d="M5 19v2M19 19v2"/></svg>"""

# Page de lancement : demande l'adresse au plugin, verifie que multiACE repond,
# puis remplace l'onglet par l'interface web de multiACE.
PAGE = r"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<style>
:root{color-scheme:dark;font:14px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
body{margin:0;min-height:100vh;display:grid;place-items:center;background:#1b1e22;color:#e9ecef}
.box{width:min(440px,90vw);text-align:center}
h1{font-size:18px;margin:0 0 6px}
p{color:#9aa3ad;margin:0 0 16px}
.row{display:flex;gap:8px;justify-content:center}
input{flex:1;background:rgba(255,255,255,.06);color:#e9ecef;border:1px solid rgba(255,255,255,.15);border-radius:6px;padding:8px 10px;font:inherit}
button{background:#009688;color:#fff;border:0;border-radius:6px;padding:8px 14px;font:inherit;cursor:pointer}
.err{color:#f08a80}
.spin{width:26px;height:26px;border:3px solid rgba(255,255,255,.15);border-top-color:#009688;border-radius:50%;margin:0 auto 14px;animation:r 1s linear infinite}
@keyframes r{to{transform:rotate(360deg)}}
</style></head><body>
<div class="box">
  <div id="wait"><div class="spin"></div><h1>Connexion à multiACE…</h1><p id="where"></p></div>
  <div id="form" hidden>
    <h1>multiACE</h1>
    <p id="why">Entre l'adresse IP de ta Snapmaker U1.</p>
    <div class="row"><input id="host" placeholder="ex. 192.168.1.50" spellcheck="false"><button id="go">Ouvrir</button></div>
  </div>
</div>
<script>
(function(){
  var $=function(i){return document.getElementById(i)};
  function post(m){if(window.orca)window.orca.postMessage(m)}
  function form(msg,host){$("wait").hidden=true;$("form").hidden=false;if(msg){$("why").textContent=msg;$("why").className="err"}if(host)$("host").value=host;$("host").focus()}
  window.orca&&window.orca.onMessage(function(m){
    if(!m)return;
    if(m.type==="open"){window.location.replace(m.url)}
    else if(m.type==="checking"){$("wait").hidden=false;$("form").hidden=true;$("where").textContent=m.host}
    else if(m.type==="ask"){form(m.error||"",m.host||"")}
  });
  $("go").onclick=function(){post({type:"open",host:$("host").value})};
  $("host").addEventListener("keydown",function(e){if(e.key==="Enter")$("go").click()});
  if(window.orca)post({type:"init"});else form("Pont OrcaSlicer indisponible.","");
})();
</script></body></html>"""


class MultiAcePage(orca.pages.PagesPluginCapabilityBase):
    """Onglet "multiACE" : affiche l'interface web de multiACE dans OrcaSlicer."""

    def on_unload(self):
        plugin_shutdown()

    def get_name(self):
        return "multiACE"

    def get_icon(self):
        path = os.path.join(storage_dir(), "multiace_icon.svg")
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(ICON_SVG)
        except OSError:
            pass
        return path

    def get_default_config(self):
        return {}

    def get_ui(self):
        return PAGE

    # Appele sur le fil de l'interface.
    def on_message(self, data):
        try:
            if isinstance(data, str):
                data = json.loads(data)
        except ValueError:
            return
        if not isinstance(data, dict):
            return
        kind = data.get("type")
        if kind == "init":
            auto_open_panel()
            host = effective_host()
            if not host:
                self.post_message({"type": "ask"})
                return
            self._check_async(host, save=False)
        elif kind == "open":
            raw = data.get("host") or ""
            host = normalize_host(raw)
            if not host:
                self.post_message({"type": "ask", "error": "Adresse invalide, par exemple 192.168.1.50", "host": raw})
                return
            self._check_async(host, save=True)

    def on_lifecycle_event(self, event, ctx):
        on_app_event(event, ctx)

    def _check_async(self, host, save):
        self.post_message({"type": "checking", "host": host})
        if save:
            # Premier contact sur le fil de l'interface : la demande d'autorisation
            # reseau d'OrcaSlicer peut s'afficher et etre memorisee.
            try:
                MultiAce(host).get_json("/version", timeout=TIMEOUT_UI)
            except PermissionError:
                self.post_message({"type": "ask", "error": permission_text(host), "host": host})
                return
            except Exception as e:
                self.post_message({"type": "ask", "error": str(e), "host": host})
                return
            save_settings(dict(load_settings(), host=host))
            self.post_message({"type": "open", "url": origin_of(host) + "/multiace/"})
            return

        def worker():
            try:
                MultiAce(host).get_json("/version", timeout=TIMEOUT_UI)
                self.post_message({"type": "open", "url": origin_of(host) + "/multiace/"})
            except PermissionError:
                self.post_message({"type": "ask", "error": permission_text(host) + " Clique Ouvrir.", "host": host})
            except Exception as e:
                self.post_message({"type": "ask", "error": str(e), "host": host})

        threading.Thread(target=worker, daemon=True).start()


# --------------------------------------------------------------------------- fenetre Preflight

POPUP = r"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#1b1e22;color:#e9ecef;
font:14px system-ui,-apple-system,"Segoe UI",sans-serif}p{color:#9aa3ad}</style></head>
<body><div style="text-align:center"><b>__NAME__</b><p>envoyé à multiACE, ouverture du Preflight…</p></div>
<script>setTimeout(function(){window.location.replace("__URL__")},300)</script></body></html>"""


class PreflightPopup:
    """Fenetre flottante avec l'interface multiACE, ouverte apres un export envoye au Preflight."""

    def __init__(self):
        self.window = None
        self.pending = None          # (nom, url, horodatage) en attente d'affichage
        self._lock = threading.Lock()

    def request(self, name, url):
        with self._lock:
            self.pending = (name, url, time.time())

    def show_pending(self):
        """A appeler hors du fil de tranchage. Ouvre la fenetre si un envoi recent attend."""
        with self._lock:
            pending, self.pending = self.pending, None
        if not pending or time.time() - pending[2] > 300:
            return
        name, url, _ = pending
        old = self.window
        if old is not None:
            try:
                if old.is_open():
                    old.close()     # on recharge pour que le Preflight reprenne le nouveau fichier
            except Exception:
                pass
        html = (POPUP.replace("__URL__", url.replace("\\", "").replace('"', ""))
                     .replace("__NAME__", name.replace("<", "").replace(">", "").replace("&", "et")))
        self.window = orca.host.ui.create_window(html=html, title="multiACE - Preflight", width=1180, height=820,
                                                 on_close=self._closed)

    def _closed(self):
        self.window = None


_POPUP = PreflightPopup()


def schedule_popup_fallback(delay=2.5):
    """Filet de securite si l'evenement de fin d'export n'arrive pas : on ouvre depuis un fil a part,
    apres la fin de l'etape de tranchage (jamais depuis le fil de tranchage lui-meme)."""
    def worker():
        time.sleep(delay)
        try:
            _POPUP.show_pending()
        except Exception:
            pass
    threading.Thread(target=worker, daemon=True).start()


# --------------------------------------------------------------------------- ancien profil 8 tetes
# Le plugin reste sur le profil Snapmaker U1 a 4 tetes : l'ancien profil « Snapmaker U1 multiACE »
# des premieres versions est seulement retire s'il est encore installe.

# Valeurs par outil du profil Snapmaker U1 d'origine (reprises de multiACE orca_profile.py).
PROFILE_NAME = "Snapmaker U1 multiACE"
BUNDLE_ID = "multiace-bridge"


def _data_dir():
    for base in (os.path.abspath(__file__), storage_dir()):
        parts = base.replace("\\", "/").split("/")
        if "orca_plugins" in parts:
            return "/".join(parts[: parts.index("orca_plugins")])
    raise RuntimeError("dossier de donnees d'OrcaSlicer introuvable")


def _user_folder(bundle):
    for collection in (bundle.printers, bundle.prints, bundle.filaments):
        for i in range(collection.size()):
            parts = os.path.normpath(collection.preset(i).file or "").replace("\\", "/").split("/")
            if "user" in parts:
                idx = parts.index("user")
                if idx + 1 < len(parts) and parts[idx + 1] != "_local":
                    return parts[idx + 1]
    return "default"


def on_multiace_profile():
    try:
        return PROFILE_NAME in (orca.host.preset_bundle().current_printer_preset().name or "")
    except Exception:
        return False


def remove_old_profile():
    """Supprime le profil "Snapmaker U1 multiACE" des anciennes versions (bundle local "multiace-bridge").

    Fil de l'interface. Ne fait rien si ce profil est l'imprimante selectionnee. Retourne True si supprime."""
    try:
        if on_multiace_profile():
            return False
        user_root = os.path.join(_data_dir(), "user")
        removed = False
        for folder in os.listdir(user_root) if os.path.isdir(user_root) else []:
            bundle_dir = os.path.join(user_root, folder, "_local", BUNDLE_ID)
            if not os.path.isdir(bundle_dir):
                continue
            for dirpath, dirnames, filenames in os.walk(bundle_dir, topdown=False):
                for name in filenames:
                    os.remove(os.path.join(dirpath, name))
                os.rmdir(dirpath)
            removed = True
        if removed:
            try:
                orca.host.preset.bundles.reload_local(BUNDLE_ID)
            except Exception:
                pass    # le profil disparait au prochain demarrage d'OrcaSlicer
        return removed
    except Exception:
        return False


# --------------------------------------------------------------------------- avant de trancher

def all_slots_from_state(state):
    """Toutes les bobines presentes (meme les couleurs deduites) : la liste des choix manuels."""
    out = []
    for ace in state.get("aces") or []:
        idx = ace.get("idx")
        if not isinstance(idx, int) or idx > 3:
            continue
        for slot in ace.get("slots") or []:
            if slot.get("state") == "empty" or slot.get("source") == "empty":
                continue
            out.append({"ace": idx, "slot": slot.get("idx"), "material": (slot.get("material") or "").strip(),
                        "color": (slot.get("color") or "").strip().lower(), "brand": slot.get("brand") or "",
                        "source": slot.get("source") or ""})
    return out


NOZZLE_FR = {"standard": "Standard", "high flow": "Haut débit", "high_flow": "Haut débit", "hybrid": "Hybride",
             "tpu high flow": "TPU haut débit", "e3d high flow": "E3D haut débit", "extra high flow": "Très haut débit"}


def _split(value):
    return [v.strip() for v in re.split(r"[;,]", value or "") if v.strip()] if value else []


def _norm_colour(c):
    """OrcaSlicer ecrit les couleurs avec la transparence (#F7D959FF) : le moteur attend #RRGGBB."""
    c = str(c or "").strip()
    m = re.fullmatch(r"#?([0-9a-fA-F]{6})(?:[0-9a-fA-F]{2})?", c)
    return "#" + m.group(1).upper() if m else c


PREP_MAX_DIST = 60      # ecart RGB max pour rapprocher une couleur d'Orca d'une bobine (au-dela : pas trouvee)


def _rgb(c):
    c = _norm_colour(c)
    return tuple(int(c[i:i + 2], 16) for i in (1, 3, 5)) if re.fullmatch(r"#[0-9A-F]{6}", c) else None


def slicing_advice(state, real, colours, orca_nozzles):
    """Assistant « avant de trancher ». Pour OrcaSlicer, le filament N est imprime par la tete TN ; en
    vrai, il part sur la tete du slot ou est sa bobine (slot 3 -> T3). Pour chacun des filaments 1-4 :
    bobine de meme couleur dans les ACE, tete reelle, buse reelle de cette tete = buse a regler pour TN
    dans OrcaSlicer pour que le tranchage corresponde a la realite.
    real : buses reelles des 4 tetes (NOZZLE_CHOICES ou "") ; colours / orca_nozzles : lus dans Orca."""
    slots = [x for x in all_slots_from_state(state) if x.get("color") and x.get("slot") is not None]
    rows, used_heads = [], {}
    for i, colour in enumerate(colours[:4]):
        want = _rgb(colour)
        now = orca_nozzles[i] if i < len(orca_nozzles) else None
        cands = []
        for x in slots:
            got = _rgb(x["color"])
            if want and got:
                d = sum((a - b) ** 2 for a, b in zip(want, got)) ** 0.5
                if d <= PREP_MAX_DIST:
                    need = real[x["slot"]] if x["slot"] < len(real) else ""
                    # la plus proche ; a egalite, celle qui ne demande rien a changer, puis l'ordre des ACE
                    cands.append((round(d), 0 if need and need == now else 1, x["ace"], x["slot"], x))
        row = {"t": i, "color": _norm_colour(colour), "now": now, "found": bool(cands)}
        if cands:
            x = min(cands, key=lambda c: c[:4])[4]
            need = real[x["slot"]] if x["slot"] < len(real) else ""
            row.update(ace=x["ace"], slot=x["slot"], head=x["slot"], need=need or None,
                       ok=bool(need) and need == now, spool_color=x["color"])
            used_heads.setdefault(x["slot"], []).append(i)
        rows.append(row)
    todo = [{"t": r["t"], "need": r["need"]} for r in rows if r["found"] and r.get("need") and not r["ok"]]
    shared = [{"head": h, "filaments": ts} for h, ts in sorted(used_heads.items()) if len(ts) > 1]
    return {"rows": rows, "todo": todo, "shared": shared, "real_known": all(real[:4]) if real else False,
            "extra": max(0, len(colours) - 4)}


_NOZZLE_CACHE = {}         # hote -> (instant, buses lues dans la U1)
NOZZLE_CACHE_S = 60.0


def effective_nozzles(client):
    """Buses vissees : lues dans la U1 quand elle les donne (valeur gardee 60 s), sinon le reglage
    « Ma U1 » du panneau, tete par tete. Retourne (liste de 4, source "u1" / "mixte" / "manuel")."""
    now = time.monotonic()
    hit = _NOZZLE_CACHE.get(client.host)
    if hit and now - hit[0] < NOZZLE_CACHE_S:
        read = hit[1]
    else:
        read = client.head_nozzle_types()
        _NOZZLE_CACHE[client.host] = (now, read)
    manual = load_settings()["real_nozzles"]
    real = [read[h] or manual[h] for h in range(4)]
    src = "u1" if all(read) else ("mixte" if any(read) else "manuel")
    return real, src


def orca_filament_setup():
    """Couleurs des filaments et buses des tetes dans OrcaSlicer (projet en cours). None si ce n'est
    pas une U1 ou si OrcaSlicer ne repond pas."""
    try:
        bundle = orca.host.preset_bundle()
        if "U1" not in (bundle.current_printer_preset().config_value("printer_model") or ""):
            return None
        colours = [c.strip().strip('"') for c in _split(bundle.full_config_value("filament_colour"))]
        nozzles = [NOZZLE_FR.get(v.strip().strip('"').lower().replace("_", " "), v.strip().strip('"'))
                   for v in _split(bundle.full_config_value("nozzle_volume_type"))]
        return colours, nozzles
    except Exception:
        return None




# --------------------------------------------------------------------------- preflight avec le code de la U1

# Methode voulue par l'auteur de multiACE (decay71/multiACE#243) : le plugin n'a AUCUNE logique
# d'attribution. Il execute dans Orca le Preflight fourni par la U1 (GET /api/preflight/pysrc : le
# post-processeur + preflight_core, exactement ce que lance l'interface web multiACE) avec le
# chargement de GET /api/preflight/livedata, puis envoie le fichier prepare a la U1.
# Si une verification echoue (code absent, trop gros, fonctions ou parametres differents de ceux
# attendus, tete en manuel...), on n'execute rien : le G-code original part dans le Preflight
# de multiACE (/api/preflight/inbox), qui fait tout lui-meme.

U1CODE_MAX = 4 * 1024 * 1024      # octets par fichier source
U1CODE_NEEDS = {
    "parse_meta": ("pp", "line_iter", "with_header"),
    "build_report": ("slicer_colors", "slicer_types", "num_aces", "plan_proxy", "live_slots", "head_ctx",
                     "token", "filename", "size", "meta", "header_text", "cost_params"),
    "rewrite_pipeline": ("src_path", "tmp_a", "tmp_b", "slicer_colors", "slicer_types", "num_aces",
                         "live_slots", "head_ctx", "mode", "meta"),
    "prepend_print_prefs": (),
}
PLAN_LABELS = {"slicer": "Comme tranché (slicer)", "optimize": "Optimisé (optimize)", "layer": "Par couche (layer)"}


class U1CodeError(Exception):
    """Verification refusee : on passe par le Preflight de multiACE."""


_u1code = {"sha": None, "pp": None, "core": None}
_u1code_lock = threading.Lock()


def _load_source(name, path):
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _check_static(core_src):
    """Lit le code sans l'executer : les fonctions et parametres attendus doivent exister."""
    import ast
    try:
        tree = ast.parse(core_src)
    except SyntaxError:
        raise U1CodeError("code de la U1 illisible")
    defs = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            a = node.args
            defs[node.name] = {x.arg for x in a.posonlyargs + a.args + a.kwonlyargs}
    for fn, params in U1CODE_NEEDS.items():
        if fn not in defs:
            raise U1CodeError("fonction %s absente : version de multiACE non prise en charge" % fn)
        missing = [p for p in params if p not in defs[fn]]
        if missing:
            raise U1CodeError("%s a changé (%s) : version de multiACE non prise en charge" % (fn, ", ".join(missing)))


def u1_code(client):
    """Telecharge et verifie le Preflight de la U1 ; renvoie (pp, core, empreinte). Leve U1CodeError."""
    import hashlib
    try:
        src = client.get_json("/preflight/pysrc", timeout=TIMEOUT_BG)
    except MultiAceError as e:
        raise U1CodeError("la U1 ne fournit pas son Preflight (%s)" % e)
    if not isinstance(src, dict):
        raise U1CodeError("réponse inattendue de /preflight/pysrc")
    pp_src, core_src, cost_src = src.get("postprocess"), src.get("core"), src.get("swap_cost")
    for label, text in (("post-processeur", pp_src), ("preflight_core", core_src)):
        if not isinstance(text, str) or not text.strip():
            raise U1CodeError("%s absent (multiACE trop ancien pour cette méthode)" % label)
    for text in (pp_src, core_src, cost_src or ""):
        if len(text.encode("utf-8")) > U1CODE_MAX:
            raise U1CodeError("code de la U1 trop gros")
    if "def match_colors_to_slots" not in pp_src or "def build_report" not in core_src:
        raise U1CodeError("code de la U1 non reconnu")
    _check_static(core_src)          # avant d'executer quoi que ce soit
    sha = hashlib.sha256((pp_src + "\0" + core_src + "\0" + (cost_src or "")).encode("utf-8")).hexdigest()
    with _u1code_lock:
        if _u1code["sha"] == sha:
            return _u1code["pp"], _u1code["core"], sha[:10]
        folder = os.path.join(storage_dir(), "u1code")
        os.makedirs(folder, exist_ok=True)
        files = {"post_process_virtual_toolheads.py": pp_src, "preflight_core.py": core_src}
        if isinstance(cost_src, str) and cost_src.strip():
            files["swap_cost.py"] = cost_src
        for fname, text in files.items():
            with open(os.path.join(folder, fname), "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
        import sys
        old = sys.dont_write_bytecode
        sys.dont_write_bytecode = True
        try:
            pp = _load_source("multiace_u1_postprocess", os.path.join(folder, "post_process_virtual_toolheads.py"))
            core = _load_source("multiace_u1_preflight_core", os.path.join(folder, "preflight_core.py"))
            if "swap_cost.py" in files and hasattr(core, "load_swap_cost"):
                core.load_swap_cost(os.path.join(folder, "swap_cost.py"))
        except Exception as e:
            raise U1CodeError("le code de la U1 ne se charge pas (%s)" % str(e)[:120])
        finally:
            sys.dont_write_bytecode = old
        for fn in U1CODE_NEEDS:
            if not callable(getattr(core, fn, None)):
                raise U1CodeError("fonction %s absente : version de multiACE non prise en charge" % fn)
        _u1code.update(sha=sha, pp=pp, core=core)
        return pp, core, sha[:10]


def _read_lines(path, size=1 << 20):
    with open(path, "r", encoding="utf-8", errors="replace", newline="") as f:
        rest = ""
        while True:
            block = f.read(size)
            text = rest + block
            if not block:
                if text:
                    yield from text.splitlines(True)
                return
            lines = text.splitlines(True)
            rest = lines.pop() if lines else ""
            yield from lines


def _live(client):
    try:
        live = client.get_json("/preflight/livedata", timeout=TIMEOUT_BG)
    except MultiAceError as e:
        if getattr(e, "status", None) == 409:
            raise U1CodeError("une tête est en mode manuel : attribution indisponible")
        raise U1CodeError("chargement illisible (%s)" % e)
    if not isinstance(live, dict) or not isinstance(live.get("live_slots"), list):
        raise U1CodeError("réponse inattendue de /preflight/livedata")
    return live


def _signature(live):
    return json.dumps([live.get("live_slots"), live.get("head_ctx")], sort_keys=True)


def u1_report(client, path, name):
    pp, core, sha = u1_code(client)
    live = _live(client)
    colors, types, naces, _used, plan, meta, header = core.parse_meta(pp, _read_lines(path), with_header=True)
    try:
        report = core.build_report(pp, slicer_colors=colors, slicer_types=types, num_aces=naces, plan_proxy=plan,
                                   live_slots=live["live_slots"], head_ctx=live.get("head_ctx") or {"mode": "multi"},
                                   token="", filename=name, size=os.path.getsize(path), meta=meta,
                                   header_text=header, cost_params=live.get("cost_params") or {})
    except Exception as e:
        if type(e).__name__ == "PreflightRejected":
            raise MultiAceError(str(e))
        raise U1CodeError("le Preflight de la U1 a échoué (%s)" % str(e)[:160])
    plans = report.get("plans") if isinstance(report, dict) else None
    if not isinstance(plans, dict) or not any(isinstance(p, dict) and p.get("feasible") for p in plans.values()):
        raise U1CodeError("ce mode de têtes se règle dans le Preflight de multiACE")
    return report, live, sha


def u1_prepare(client, path, name, plan_name, prefs, expected):
    """Recalcule avec le chargement du moment, ecrit le G-code pret a imprimer, le verifie."""
    pp, core, _sha = u1_code(client)
    live = _live(client)
    if _signature(live) != expected:
        raise MultiAceError("les bobines ont changé depuis l'analyse : vérifie la nouvelle proposition")
    folder = os.path.join(storage_dir(), "u1run")
    os.makedirs(folder, exist_ok=True)
    tmp_a, tmp_b = os.path.join(folder, "a.gcode"), os.path.join(folder, "b.gcode")
    colors, types, naces, _used, _plan, meta = core.parse_meta(pp, _read_lines(path))
    final = core.rewrite_pipeline(pp, src_path=path, tmp_a=tmp_a, tmp_b=tmp_b, slicer_colors=colors,
                                  slicer_types=types, num_aces=naces, live_slots=live["live_slots"],
                                  head_ctx=live.get("head_ctx") or {"mode": "multi"}, mode=plan_name,
                                  meta=meta)
    if prefs.get("bed") or prefs.get("cam") or prefs.get("flow"):
        other = tmp_b if final == tmp_a else tmp_a
        core.prepend_print_prefs(final, other, bool(prefs.get("bed")), bool(prefs.get("cam")), bool(prefs.get("flow")))
        final = other
    # Verifications du fichier produit avant tout envoi.
    if not os.path.exists(final) or os.path.getsize(final) < 1024:
        raise MultiAceError("fichier préparé vide")
    facts = gcode_facts(final)
    if not facts["processed"]:
        raise MultiAceError("le fichier préparé n'a pas la marque multiACE : envoi annulé")
    if hasattr(core, "used_ace_slots_file"):
        present = {(s.get("ace"), s.get("slot")) for s in live["live_slots"]}
        used = {tuple(x) for x in core.used_ace_slots_file(final) or []}
        if not used <= present:
            raise MultiAceError("le fichier utilise une bobine absente : envoi annulé")
    return final


U1_PAGE = r"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<style>
body{margin:0;background:#15181c;color:#e8eeef;font:14px/1.45 "Segoe UI",Inter,Arial,sans-serif}
.w{padding:18px 20px}h1{font-size:18px;margin:0 0 4px}.sub{color:#8fa3a5;font-size:12px;margin-bottom:12px}
.card{background:#1d2228;border:1px solid #2a3138;border-radius:10px;padding:12px 14px;margin:10px 0}
.warn{border-color:#8a6d1f;background:#2a2414}.err{border-color:#8a2b2b;background:#2a1717}.ok{border-color:#1f6b5f;background:#13302b}
label.plan{display:flex;gap:10px;align-items:center;padding:6px 0;cursor:pointer}
table{border-collapse:collapse;width:100%;margin-top:6px}td,th{padding:4px 6px;text-align:left;font-size:13px}th{color:#8fa3a5;font-weight:600}
.sw{display:inline-block;width:14px;height:14px;border-radius:50%;border:1px solid #0006;vertical-align:-2px;margin-right:6px}
.btns{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}button{background:#24303a;color:#e8eeef;border:1px solid #33414c;border-radius:8px;padding:8px 14px;font:inherit;cursor:pointer}
button.main{background:#3fd0bf;color:#0d2a26;border-color:#3fd0bf;font-weight:600}button:disabled{opacity:.45;cursor:default}
.opts label{margin-right:16px}.muted{color:#8fa3a5}
</style></head><body><div class="w" id="app"></div>
<script>
var D=__DATA__;
(function(){
function esc(s){return String(s==null?"":s).replace(/[&<>"']/g,function(c){return{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]})}
function col(c){var m=/^#?([0-9a-fA-F]{6})/.exec(String(c||""));return m?"#"+m[1]:"#777"}
var sel=null,busy=false,msg=null;
function post(m){try{window.orca.postMessage(m)}catch(e){try{window.chrome.webview.postMessage(m)}catch(_){}}}
function render(){
  var a=document.getElementById("app"),h='<h1>multiACE Preflight : '+esc(D.name||"")+'</h1>';
  h+='<div class="sub">Calcul fait par le code multiACE de ta U1'+(D.version?' (version '+esc(D.version)+')':'')+(D.sha?' · '+esc(D.sha):'')+'. Le plugin ne choisit rien lui-même.</div>';
  if(D.banner)h+='<div class="card warn">'+esc(D.banner)+'</div>';
  if(D.loading)h+='<div class="card">'+esc(D.loading)+'</div>';
  if(D.error)h+='<div class="card err">'+esc(D.error)+'</div>';
  var r=D.report;
  if(r){
    if(r.missing_materials&&r.missing_materials.length)h+='<div class="card err">Matière absente des ACE : '+esc(JSON.stringify(r.missing_materials))+'</div>';
    if(r.nozzles_mixed)h+='<div class="card warn">Buses de diamètres différents dans ce fichier : vérifie la proposition.</div>';
    var names={};(r.slicer_colors||[]).forEach(function(c){names[c.t]=c});
    var order=["slicer","optimize","layer"];h+='<div class="card">';
    order.forEach(function(k){var p=(r.plans||{})[k];if(!p)return;if(sel===null&&p.feasible)sel=k;
      h+='<label class="plan"><input type="radio" name="p" value="'+k+'"'+(sel===k?' checked':'')+(p.feasible?'':' disabled')+'> <b>'+esc(D.labels[k]||k)+'</b> <span class="muted">'+(p.feasible?(p.swaps+' échange(s) de bobine'):esc(p.reason||'impossible'))+'</span></label>';});
    var p=(r.plans||{})[sel];
    if(p&&p.mapping&&p.mapping.length){h+='<table><tr><th>Filament</th><th>Bobine</th></tr>';
      p.mapping.forEach(function(m){var c=names[m.t]||{},s=m.slot;h+='<tr><td><span class="sw" style="background:'+col(c.hex)+'"></span>'+(m.t+1)+' · '+esc(c.material||"")+' '+esc(c.name||"")+'</td><td>'+(s?('<span class="sw" style="background:'+col(s.color)+'"></span>ACE '+(s.ace+1)+' · slot '+(s.slot+1)+' · '+esc(s.material||"")):'<span class="muted">aucune</span>')+(m.loose_mat?' <span class="muted">(matière différente)</span>':'')+(/fuzzy|fallback|base|canon/.test(m.tier||'')?' <span class="muted">(couleur approchante)</span>':'')+'</td></tr>'});
      h+='</table>';}
    h+='</div><div class="card opts"><b>Au lancement</b> (préférences multiACE)<br><label><input type="checkbox" id="bed"'+(D.prefs.bed?' checked':'')+'> Maillage du plateau</label><label><input type="checkbox" id="flow"'+(D.prefs.flow?' checked':'')+'> Calibration du flux</label><label><input type="checkbox" id="cam"'+(D.prefs.cam?' checked':'')+'> Time-lapse</label></div>';
  }
  if(msg)h+='<div class="card '+(msg.ok?'ok':'err')+'">'+esc(msg.text)+'</div>';
  h+='<div class="btns">';
  if(r)h+='<button class="main" id="go"'+(busy||!sel?' disabled':'')+'>Imprimer</button>';
  h+='<button id="pf"'+(busy?' disabled':'')+'>Ouvrir dans le Preflight multiACE</button><button id="x">Fermer</button></div>';
  a.innerHTML=h;
  Array.prototype.forEach.call(document.querySelectorAll('input[name=p]'),function(i){i.onchange=function(){sel=i.value;render()}});
  var g=document.getElementById("go");if(g)g.onclick=function(){busy=true;msg=null;render();post({a:"print",plan:sel,bed:document.getElementById("bed").checked,flow:document.getElementById("flow").checked,cam:document.getElementById("cam").checked})};
  document.getElementById("pf").onclick=function(){busy=true;msg=null;render();post({a:"preflight"})};
  document.getElementById("x").onclick=function(){post({a:"close"})};
}
window.__orca_on_message=function(m){if(m.type==="data"){D=m.data;sel=null;busy=false}else if(m.type==="done"){busy=false;msg=m;if(m.final)busy=true}render()};
try{window.orca.onMessage(window.__orca_on_message)}catch(e){}
render();
})();
</script></body></html>"""


class U1PreflightWindow:
    """Proposition calculee par le code de la U1 ; verifie tout avant d'envoyer."""

    def __init__(self):
        self.window = None
        self.job = None
        self.live_sig = None
        self.prefs = {"bed": True, "flow": False, "cam": False}
        self._lock = threading.Lock()

    def start(self, path, name, host, delay=1.0):
        with self._lock:
            self.job = {"path": path, "name": name, "host": host, "id": time.time()}
            job = self.job

        def worker():
            time.sleep(delay)
            if self.job is not job or _STOP.is_set():
                return
            self._send({"name": name, "loading": "Préparation avec le code multiACE de la U1…"})
            client = MultiAce(host)
            version = ""
            try:
                version = str(client.state(timeout=TIMEOUT_BG).get("version") or "")
            except Exception:
                pass
            try:
                report, live, sha = u1_report(client, path, name)
            except U1CodeError as e:
                self._fallback(job, "Vérification : %s. Le fichier d'origine part dans le Preflight de multiACE." % e)
                return
            except PermissionError:
                self._send({"name": name, "error": permission_text(host)})
                return
            except Exception as e:
                self._send({"name": name, "error": "Analyse impossible : %s" % e})
                return
            if self.job is not job:
                return
            self.live_sig = _signature(live)
            self._send({"name": name, "version": version, "sha": sha, "report": report, "labels": PLAN_LABELS,
                        "prefs": self.prefs})

        threading.Thread(target=worker, daemon=True).start()

    def _fallback(self, job, text):
        try:
            MultiAce(job["host"]).send_gcode(job["path"], job["name"])
            _POPUP.request(job["name"], origin_of(job["host"]) + "/multiace/")
            _POPUP.show_pending()
            self._send({"name": job["name"], "banner": text})
        except Exception as e:
            self._send({"name": job["name"], "error": "%s Envoi impossible : %s" % (text, e)})

    def _send(self, data):
        data.setdefault("labels", PLAN_LABELS)
        data.setdefault("prefs", self.prefs)
        w = self.window
        if w is not None:
            try:
                if w.is_open():
                    w.post({"type": "data", "data": data})
                    return
            except Exception:
                pass
        payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
        self.window = orca.host.ui.create_window(html=U1_PAGE.replace("__DATA__", payload),
                                                 title="multiACE - Preflight de la U1", width=760, height=680,
                                                 on_message=self.on_message, on_close=self._closed)

    def _closed(self):
        self.window = None

    def _reply(self, ok, text, final=False):
        w = self.window
        if w is not None:
            try:
                w.post({"type": "done", "ok": ok, "text": text, "final": final})
            except Exception:
                pass

    def on_message(self, m):
        if not isinstance(m, dict) or not self.job:
            return
        a = m.get("a")
        if a == "close":
            w = self.window
            if w is not None:
                try:
                    w.close()
                except Exception:
                    pass
            return
        if a == "preflight":
            threading.Thread(target=self._to_preflight, daemon=True).start()
        elif a == "print" and m.get("plan") in PLAN_LABELS:
            self.prefs = {k: m.get(k) is True for k in ("bed", "flow", "cam")}
            threading.Thread(target=self._print, args=(m["plan"], dict(self.prefs)), daemon=True).start()

    def _to_preflight(self):
        job = self.job
        try:
            MultiAce(job["host"]).send_gcode(job["path"], job["name"])
            _POPUP.request(job["name"], origin_of(job["host"]) + "/multiace/")
            _POPUP.show_pending()
            self._reply(True, "Fichier d'origine envoyé au Preflight multiACE.")
        except PermissionError:
            self._reply(False, permission_text(job["host"]))
        except Exception as e:
            self._reply(False, "Échec : %s" % e)

    def _print(self, plan_name, prefs):
        job = self.job
        client = MultiAce(job["host"])
        try:
            state = client.state(timeout=TIMEOUT_UI)
            ps = str(state.get("printer_state") or "").lower()
            if ps in ("printing", "paused") or state.get("swap_in_progress"):
                raise MultiAceError("la U1 est occupée (%s)" % (ps or "échange en cours"))
            final = u1_prepare(client, job["path"], job["name"], plan_name, prefs, self.live_sig)
            base, ext = os.path.splitext(os.path.basename(job["name"]))
            client.send_gcode(final, base + "_multiACE" + (ext or ".gcode"), endpoint="/upload-and-print")
            self._reply(True, "Impression lancée avec le plan « %s »." % PLAN_LABELS[plan_name], final=True)
        except U1CodeError as e:
            self._reply(False, "Vérification : %s. Utilise « Ouvrir dans le Preflight multiACE »." % e)
        except PermissionError:
            self._reply(False, permission_text(job["host"]))
        except Exception as e:
            if "ont changé" in str(e):
                self.start(job["path"], job["name"], job["host"], delay=0)
            self._reply(False, "Envoi annulé : %s" % e)


_U1PF = U1PreflightWindow()


# --------------------------------------------------------------------------- pipeline

_recent_sends = {}


class SendToPreflight(orca.slicing.SlicingPipelineCapabilityBase):
    """Process > Autres > Slicing Pipeline Plugin > "multiACE : envoyer au Preflight"."""

    def on_unload(self):
        plugin_shutdown()

    def get_name(self):
        return "multiACE : envoyer au Preflight"

    def get_default_config(self):
        # also_on_print : envoyer aussi quand on clique Imprimer / Envoyer a l'imprimante,
        #                 et bloquer alors l'envoi direct d'OrcaSlicer.
        # min_filaments : n'envoyer que si au moins N filaments sont utilises (1 = toujours).
        return {"also_on_print": False, "min_filaments": 1}

    def _config(self):
        cfg = self.get_default_config()
        try:
            stored = json.loads(self.get_config())
            if isinstance(stored, dict):
                cfg.update({k: stored[k] for k in cfg if k in stored})
        except (TypeError, ValueError):
            pass
        return cfg

    def execute(self, ctx):
        if ctx.step != orca.slicing.Step.psGCodePostProcess:
            return orca.ExecutionResult.success()
        path = getattr(ctx, "gcode_path", "") or ""
        if not path or not os.path.exists(path):
            return orca.ExecutionResult.skipped("multiACE : pas de fichier G-code")
        cfg = self._config()
        target = (getattr(ctx, "host", "") or "").strip()
        to_printer = target not in ("", "File")
        u1code = load_settings().get("u1_code", True)
        if to_printer and not u1code and not cfg.get("also_on_print"):
            return orca.ExecutionResult.skipped("multiACE : envoi direct a l'imprimante, Preflight non utilise")

        name = os.path.basename((getattr(ctx, "output_name", "") or "").strip() or path)
        try:
            facts = gcode_facts(path)
        except OSError as e:
            return orca.ExecutionResult.failure(orca.PluginResult.RecoverableError, "multiACE : lecture du G-code impossible (%s)" % e)
        if facts["processed"]:
            return orca.ExecutionResult.skipped("multiACE : G-code deja traite par multiACE (script de post-traitement actif ?), non envoye")
        if facts["u1control"]:
            return orca.ExecutionResult.failure(
                orca.PluginResult.RecoverableError,
                "multiACE : ce G-code a ete modifie par U1 Control (\"U1 print setup\"). Decoche-le pour ce profil "
                "afin que multiACE recoive l'export original.")
        used = facts["filaments_used"]
        try:
            minimum = int(cfg.get("min_filaments") or 1)
        except (TypeError, ValueError):
            minimum = 1
        if used is not None and used < minimum:
            return orca.ExecutionResult.skipped("multiACE : %d filament(s) utilise(s), envoi reserve a %d et plus" % (used, minimum))

        size = os.path.getsize(path)
        key = (name, size)
        now = time.time()
        # L'etape peut tourner deux fois de suite pour un meme export : on ignore le doublon immediat.
        if now - _recent_sends.get(key, 0) < 90:
            return orca.ExecutionResult.skipped("multiACE : deja traite")

        kept = False
        try:
            keep_last_gcode(path, name)     # copie : Preflight de la U1, et « renvoyer le dernier G-code »
            kept = True
        except OSError:
            pass

        host = normalize_host(load_settings()["host"])
        if not host:
            try:
                host = normalize_host(ctx.config_value("print_host"))
            except Exception:
                host = ""
        if not host:
            return orca.ExecutionResult.failure(orca.PluginResult.RecoverableError,
                                                "multiACE : adresse de la U1 inconnue : renseigne-la dans le panneau ACE (Options → Adresse de la U1)")
        if u1code and kept:
            _recent_sends[key] = now
            _U1PF.start(last_gcode_paths()[0], name, host)
            if to_printer:
                return orca.ExecutionResult.failure(
                    orca.PluginResult.FatalError,
                    "multiACE : impression préparée par le Preflight de la U1 (envoi direct d'OrcaSlicer annulé, c'est normal).")
            return orca.ExecutionResult.success("multiACE : préparation avec le code multiACE de la U1 pour \"%s\"" % name)
        try:
            MultiAce(host).send_gcode(path, name)
        except PermissionError:
            return orca.ExecutionResult.failure(
                orca.PluginResult.RecoverableError,
                "multiACE : acces reseau non autorise depuis le tranchage. Ouvre l'onglet multiACE, clique "
                "Enregistrer pour autoriser %s, puis renvoie depuis l'onglet." % (origin_of(host) or "la U1"))
        except Exception as e:
            return orca.ExecutionResult.failure(
                orca.PluginResult.RecoverableError,
                "multiACE : envoi au Preflight impossible (%s). Le G-code est garde : renvoie-le depuis l'onglet multiACE." % e)
        _recent_sends[key] = now
        if not to_printer and load_settings().get("popup", True):
            _POPUP.request(name, origin_of(host) + "/multiace/")
            schedule_popup_fallback()

        message = "multiACE : \"%s\" envoye au Preflight de %s%s" % (
            name, host, (" (%d filaments)" % used) if used else "")
        if to_printer:
            # Envoye au Preflight : on arrete l'envoi direct pour que l'impression ne parte pas deux fois.
            return orca.ExecutionResult.failure(
                orca.PluginResult.FatalError,
                message + ". Envoi direct d'OrcaSlicer annule : lance l'impression depuis le Preflight multiACE.")
        return orca.ExecutionResult.success(message)


# --------------------------------------------------------------------------- panneau ACE

PANEL = r"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<style>
:root{--fg:var(--orca-fg,#e9ecef);--muted:var(--orca-muted,#9aa3ad);--line:var(--orca-border,rgba(255,255,255,.12));
  --accent:#009688;--bad:#e05a4f;--warn:#e0a030;color-scheme:dark;font:12.5px/1.4 system-ui,-apple-system,"Segoe UI",sans-serif}
*{box-sizing:border-box}
body{margin:0;padding:10px 10px 30px;color:var(--fg)}
.top{display:flex;align-items:center;gap:6px;margin-bottom:8px}
.top b{font-size:13.5px;flex:1}
.pill{font-size:11px;border-radius:999px;padding:2px 8px;background:rgba(255,255,255,.08);color:var(--muted)}
.pill.ok{background:rgba(63,178,127,.18);color:#3fb27f}.pill.bad{background:rgba(224,90,79,.18);color:var(--bad)}
.pill.warn{background:rgba(224,160,48,.18);color:var(--warn)}
h4{margin:12px 0 6px;font-size:11px;letter-spacing:.7px;text-transform:uppercase;color:var(--muted);display:flex;align-items:center;gap:6px}
h4 span{flex:1}
.item{display:flex;align-items:center;gap:8px;padding:5px 2px;border-top:1px solid var(--line)}
.sw{width:18px;height:18px;border-radius:50%;flex:none;border:1px solid rgba(255,255,255,.25)}
.sw.empty{background:repeating-linear-gradient(45deg,transparent 0 3px,rgba(255,255,255,.12) 3px 5px)}
.t{flex:1;min-width:0}.t small{display:block;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
button{background:transparent;color:var(--fg);border:1px solid var(--line);border-radius:5px;padding:3px 8px;font:inherit;font-size:11.5px;cursor:pointer;white-space:nowrap}
button.go{border-color:rgba(0,150,136,.6);color:#4fd1c0}
button.arm{background:var(--warn);border-color:var(--warn);color:#1b1e22}
button:disabled{opacity:.35;cursor:default}
.msg{margin:8px 0;padding:7px 9px;border-radius:6px;display:none;font-size:12px}
.hostbox{border-color:#8a6d1f}.hosthint{font-size:12px;opacity:.8;margin:4px 0 8px}.hostrow{display:flex;gap:6px}.hostrow input{flex:1;min-width:0;background:#11151a;color:inherit;border:1px solid #3a444e;border-radius:6px;padding:5px 7px}.hostline{font-size:12px;margin:2px 0 6px;display:flex;gap:6px;align-items:center;flex-wrap:wrap}
select option{background:#22262c;color:#e8eaed}
.sppick{position:relative}.spbtn{width:100%;text-align:left;display:flex;align-items:center;gap:6px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.splist{display:none;position:absolute;z-index:20;left:0;right:0;top:100%;margin-top:2px;max-height:260px;overflow:auto;background:#1c1f24;border:1px solid rgba(255,255,255,.15);border-radius:6px;box-shadow:0 6px 18px rgba(0,0,0,.5)}
.splist.show{display:block}.spo{display:flex;align-items:center;gap:8px;padding:6px 8px;cursor:pointer;font-size:12px;color:#e8eaed}
.spo:hover{background:rgba(255,255,255,.08)}.spo.on{background:rgba(0,150,136,.18)}.spo.new{color:#4fd1c0}
.spl{display:flex;flex-direction:column;line-height:1.25}.spl small{color:#9aa4b2}
.calib{display:flex;align-items:center;gap:8px;font-size:12px;margin:2px 0 10px;padding:6px 8px;border:1px solid rgba(255,255,255,.08);border-radius:6px}.calib span{flex:1}
.ah{display:flex;align-items:center;gap:6px;font-size:12px;color:var(--mut,#9aa4b2);margin:-2px 0 8px;cursor:pointer}
.queue{display:none;margin:0 0 8px;padding:7px 9px;border-radius:6px;background:rgba(255,255,255,.05);font-size:12px}
.queue.show{display:block}.queue,.item button,button{user-select:none;-webkit-user-select:none}
.t small.plan{color:#4fd1c0}.queue ol{margin:4px 0 6px 18px;padding:0}.queue li{margin:2px 0}
.queue li.run{color:#4fd1c0;font-weight:600}.queue li.fail{color:#f08a80}.queue .x{background:none;border:0;color:#9aa4b2;cursor:pointer;padding:0 4px}
.queue .qb{font-size:11px;padding:3px 8px;margin-right:6px}
.msg.show{display:block}.msg.info{background:rgba(0,150,136,.15)}.msg.err{background:rgba(224,90,79,.15)}
.badge{font-size:10.5px;border-radius:4px;padding:0 5px;background:rgba(255,255,255,.08);color:var(--muted)}
.badge.derived{color:var(--warn)}
.note{color:var(--muted);font-size:11.5px}
.prep{margin:4px 0 8px;padding:7px 8px;border-radius:8px;background:rgba(255,255,255,.04)}
.ph{margin:0 0 4px}.ng{display:grid;grid-template-columns:1fr 1fr;gap:4px;margin:4px 0 6px}
.nc{padding:4px 6px;border-radius:5px;background:rgba(255,255,255,.05);font-size:11.5px;color:var(--muted)}
.nc.chg{background:rgba(224,160,48,.28);color:#ffd27a;font-weight:700}
details.pf{margin-top:4px}details.pf summary{cursor:pointer;color:var(--muted);font-size:11px}
.rn{display:flex;flex-wrap:wrap;gap:4px 8px;margin:6px 0;font-size:11.5px;color:var(--muted);align-items:center}
.rn select{background:#1c1f24;color:var(--fg);border:1px solid var(--line);border-radius:5px;font:inherit;font-size:11px;padding:1px 2px}
.pr{display:flex;gap:6px;align-items:flex-start;padding:3px 0;font-size:11.5px}.pr .sw{width:14px;height:14px;margin-top:1px}
.pw{color:var(--warn);margin:4px 0}.pok{color:#3fb27f;margin:4px 0}.okc{color:#3fb27f}.warnc{color:var(--warn)}
.dry{display:flex;flex-wrap:wrap;align-items:center;gap:5px;padding:5px 2px 7px;font-size:11.5px;color:var(--muted)}
.dry b{color:var(--fg);font-weight:600}
.dry.on b{color:#f0a35a}
.dry select{background:rgba(255,255,255,.06);color:var(--fg);border:1px solid var(--line);border-radius:5px;padding:2px 4px;font:inherit;font-size:11.5px}
.qty{font-variant-numeric:tabular-nums}
.top button{padding:3px 7px}
.top button.on{border-color:rgba(0,150,136,.7);color:#4fd1c0}
.screen{margin:4px 0 8px;position:relative}
.cam img{display:block;width:100%;aspect-ratio:16/9;object-fit:cover;border-radius:10px;border:1px solid var(--line);background:#000}
.cam{position:relative;margin:4px 0 8px}.cam .live{position:absolute;left:8px;top:7px;font-size:10px;font-weight:700;color:#fff;background:rgba(224,60,60,.85);border-radius:4px;padding:1px 5px}
.cam .err{font-size:11.5px;color:var(--muted);padding:10px;border:1px dashed var(--line);border-radius:8px;text-align:center}
.screen img{display:block;width:100%;border-radius:8px;border:1px solid var(--line);cursor:pointer;background:#000;image-rendering:auto}
.screen .err{font-size:11.5px;color:var(--muted);padding:10px;border:1px dashed var(--line);border-radius:8px;text-align:center}
#mini{display:flex;gap:6px;align-items:center;flex-wrap:wrap;padding:4px 0 6px}
#mini[hidden]{display:none}
#mini .h{display:flex;align-items:center;gap:4px;font-size:11.5px}
#mini .sw{width:14px;height:14px}
body.compact #foot,body.compact #mc,body.compact #mcH{display:none}
.item.click{cursor:pointer}.item.click:hover{background:rgba(255,255,255,.03)}
.ed{border:1px solid var(--line);border-radius:7px;padding:8px;margin:2px 0 8px;display:grid;grid-template-columns:auto 1fr;gap:6px 8px;align-items:center;font-size:11.5px}
.ed label{color:var(--muted)}
.ed input,.ed select{background:rgba(255,255,255,.06);color:var(--fg);border:1px solid var(--line);border-radius:5px;padding:3px 6px;font:inherit;font-size:11.5px;min-width:0}
.ed input[type=color]{padding:0;width:34px;height:24px;border-radius:4px}
.ed .full{grid-column:1/-1;display:flex;gap:6px;align-items:center;flex-wrap:wrap}
.ed .sw2{display:flex;gap:4px;flex-wrap:wrap}.ed .sw2 i{width:16px;height:16px;border-radius:50%;cursor:pointer;border:1px solid rgba(255,255,255,.25)}
.bar{height:3px;border-radius:2px;background:rgba(255,255,255,.1);margin-top:3px;overflow:hidden}.bar i{display:block;height:100%;background:#4fd1c0}

/* ---- habillage v0.28 */
body{background:radial-gradient(130% 50% at 0% 0%,rgba(0,150,136,.10),transparent 60%),radial-gradient(120% 40% at 100% 100%,rgba(122,167,255,.06),transparent 60%)}
.top b{font-size:16px;letter-spacing:.4px;background:linear-gradient(90deg,#4fd1c0,#7aa7ff);-webkit-background-clip:text;background-clip:text;color:transparent}
button{border-radius:999px;padding:4px 11px;transition:background .15s,border-color .15s}
button:hover:not(:disabled){background:rgba(255,255,255,.07)}
button.go{background:rgba(0,150,136,.16);border-color:rgba(0,150,136,.5);color:#5fe0cf}
button.go:hover:not(:disabled){background:rgba(0,150,136,.28)}
.top button{border-radius:8px}
.card{background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.07);border-radius:12px;padding:8px 10px 10px;margin:0 0 10px;box-shadow:0 4px 14px rgba(0,0,0,.18)}
.card h4{margin:2px 0 8px}
.prep{border:1px solid rgba(255,255,255,.07);border-radius:12px;padding:8px 10px}
.heads{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:8px}
.htile{border-radius:10px;padding:8px;background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.06);display:flex;flex-direction:column;gap:3px;min-width:0}
.htile.on{background:linear-gradient(155deg,var(--tint),rgba(255,255,255,.025) 75%)}
.hrow{display:flex;align-items:center;gap:8px;min-width:0}.hrow>div{min-width:0}
.hn{font-size:15px;font-weight:700;line-height:1.1}
.hm{font-size:11.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.htile small{display:block;color:var(--muted);font-size:10.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.htile small.plan{color:#4fd1c0}
.htile button{margin-top:4px;width:100%;font-size:11px;padding:3px 6px}
.spool{border-radius:50%;flex:none;background:radial-gradient(circle,#1b1e22 0 22%,rgba(255,255,255,.35) 23% 26%,var(--c) 28% 100%)}
.spool.empty{background:repeating-linear-gradient(45deg,transparent 0 3px,rgba(255,255,255,.12) 3px 5px);box-shadow:0 0 0 1px rgba(255,255,255,.15)}
.ace .item{border-top:1px solid rgba(255,255,255,.06);border-radius:8px;padding:6px 4px}
.ace .item.click:hover{background:rgba(255,255,255,.04)}
.ace .bar{height:4px;border-radius:3px;margin-top:4px;max-width:160px}
h4 span.hum{flex:none}.tmp{background:rgba(122,167,255,.14);color:#9cbcff}.hum{font-size:10.5px;border-radius:999px;padding:1px 8px;font-weight:600;text-transform:none;letter-spacing:0}
.hum.ok{background:rgba(63,178,127,.18);color:#5fd39a}.hum.mid{background:rgba(224,160,48,.18);color:#f0b45a}.hum.hi{background:rgba(224,90,79,.2);color:#f08a80}
.dry{border-radius:8px;padding:6px 8px;margin:0 0 4px;background:rgba(255,255,255,.03)}
.dry.on{background:linear-gradient(90deg,rgba(240,140,60,.16),rgba(240,140,60,.04))}
.dprog{flex-basis:100%;height:3px;border-radius:2px;background:rgba(255,255,255,.08);overflow:hidden}.dprog i{display:block;height:100%;background:linear-gradient(90deg,#f0a35a,#f06a4a)}
.calib{border-radius:10px;background:rgba(255,255,255,.03)}
.optscard .ah{margin:5px 0}.optscard h4 button{padding:2px 8px}
#foot{opacity:.75}
h4.fh{cursor:pointer;user-select:none}h4.fh:hover{color:var(--fg)}
.chev{display:inline-block;width:12px;font-style:normal;color:var(--muted);transition:transform .15s}
.folded .chev{transform:rotate(-90deg)}
.card.folded{padding-bottom:6px}.card.folded>:not(h4){display:none}.card.folded h4{margin-bottom:0}
.fmini{display:inline-flex;gap:4px;vertical-align:middle;margin-left:6px}
.fmini .spool{box-shadow:0 0 0 1px rgba(255,255,255,.15)!important}
.prep.folded .pbody{display:none}
[data-pk]{cursor:pointer}.mrow .sl[data-pk]:hover .spool,.fmini [data-pk]:hover{filter:brightness(1.25)}
.pop{position:fixed;z-index:60;min-width:170px;max-width:240px;background:#23272d;border:1px solid rgba(255,255,255,.16);border-radius:10px;padding:9px;box-shadow:0 10px 28px rgba(0,0,0,.55)}
.pop .pt{display:flex;align-items:center;gap:8px;font-weight:600;font-size:12px}.pop .pt small{display:block;font-weight:400;color:var(--muted);font-size:10.5px}
.pop button{display:block;width:100%;margin-top:7px}.pop .pn{color:var(--muted);font-size:10.5px;margin-top:6px}.prep .ptitle{cursor:pointer;user-select:none;font-weight:600}
.pmv{float:right;border:0;background:none;color:var(--muted);font-size:10.5px;padding:0 2px;margin-top:-1px}
.pmv:hover:not(:disabled){background:none;color:var(--fg)}
#mini{display:block;padding:2px 0 6px}
.mrow{display:flex;align-items:center;gap:6px;padding:6px 8px;margin:0 0 6px;border-radius:10px;background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.07)}
.mrow .lab{font-size:11px;font-weight:700;color:var(--muted);width:40px;flex:none}
.mrow .sl{display:flex;flex-direction:column;align-items:center;gap:1px;flex:1;min-width:0}
.mrow .sl small{font-size:9.5px;color:var(--muted);line-height:1}.mrow .sl small.on{color:#5fe0cf;font-weight:700}
.mrow .info{display:flex;flex-direction:column;align-items:flex-end;gap:2px;flex:none;font-size:10px;color:#f0a35a}
.mprep{font-size:11px;margin:0 0 6px;padding:4px 8px;border-radius:8px}
.mprep.ok{color:#5fd39a;background:rgba(63,178,127,.10)}.mprep.todo{color:#f0b45a;background:rgba(224,160,48,.12)}
</style></head><body>
<div class="top"><b>ACE</b><span id="st" class="pill">…</span>
  <button id="cam" title="Caméra de la U1 : masquée / en haut / en bas">📷</button>
  <button id="scr" title="Écran de la U1 : masqué / en haut / en bas">▣</button>
  <button id="cmp" title="Réduire / agrandir">–</button>
  <button id="hd" title="Masquer le panneau (une notification permet de le rouvrir)">⇥</button>
  <button id="opt" title="Options (adresse de la U1, homing, garde-fou, export)">⚙</button>
  <button id="rf" title="Actualiser">↻</button></div>
<div id="screenTop"></div><div id="camTop"></div>
<div id="msg" class="msg"></div>
<div id="optsCard" class="card optscard" hidden><h4><span>⚙ Options</span><button id="optX" class="ghost" title="Fermer les options">✕</button></h4>
<div class="hostline">Adresse de la U1 : <b id="hostCur">—</b> <button id="hostEdit" class="ghost">Modifier</button></div>
<label class="ah" title="Si la U1 n'a pas fait son homing, le plugin le fait tout seul avant de charger / échanger / décharger, sans te demander."><input type="checkbox" id="ah"> Homing automatique si nécessaire</label>
<label class="ah" title="Si un ACE se déconnecte puis revient : le plugin relance son séchage là où il en était, et pendant une impression il relance la poussée du filament, uniquement pour la tête qui imprime (si multiACE ne l'a pas déjà fait)."><input type="checkbox" id="gf"> Garde-fou : relancer après une déconnexion d'ACE</label><label class="ah" title="À l'export, le plugin exécute dans Orca le Preflight fourni par ta U1 (code multiACE de ta version), vérifie tout puis imprime. Décoché : le fichier d'origine part dans le Preflight de multiACE, sans rien exécuter."><input type="checkbox" id="uc"> Préparer l'export avec le code multiACE de la U1</label>

</div>
<div id="hostbox" class="card hostbox" hidden><b id="hostTitle">Adresse de la U1 introuvable</b>
<div class="hosthint">Entre l'adresse IP de ta U1 (affichée dans ses réglages réseau, par exemple 192.168.1.50).</div>
<div class="hostrow"><input id="hostIn" placeholder="192.168.1.50" spellcheck="false"><button id="hostOk">Enregistrer</button><button id="hostX" class="ghost">Annuler</button></div></div>
<div id="queue" class="queue"></div>
<div id="mini" hidden></div>
<div id="full">
<div id="prepTop"><div id="prep"></div></div>
<div class="card" id="headsCard">
<h4 class="fh" data-fold="heads"><span><i class="chev">▾</i>Têtes<span id="headsMini" class="fmini"></span></span><button id="ua">Tout décharger</button></h4>
<div id="heads" class="heads"></div>
<div class="calib"><span>Calibration du plateau</span><select id="bt" title="Température du plateau pendant la mesure">
<option value="55" selected>55 °C</option><option value="60">60 °C</option><option value="70">70 °C</option><option value="80">80 °C</option><option value="100">100 °C</option></select>
<button data-act="calbed" title="Chauffe le plateau, attend 2 min, mesure le maillage (AUTO_BED_MESH_CALIBRATE) ; la U1 l'enregistre">Lancer</button></div>
</div>
<div id="aces"></div>
<div id="prepBottom"></div>
</div>
<div id="camBottom"></div><div id="screenBottom"></div>
<p class="note" id="foot">Clique sur une bobine pour modifier sa couleur, sa matière ou son poids. Clique deux fois sur un bouton pour confirmer une action. Charger / échanger / décharger / sécher / calibrer s’enchaînent dans une file d’attente (« Arrêter » le séchage part tout de suite).<br><span style="opacity:.6">multiACE Bridge v__VERSION__</span></p>
<script>
(function(){
  var $=function(i){return document.getElementById(i)};
  var S={base:1,busy:false,locked:false,armed:null,dt:{},dd:{},edit:null,last:null};
  function esc(x){var d=document.createElement("span");d.textContent=x==null?"":String(x);return d.innerHTML}
  function post(m){window.orca&&window.orca.postMessage(m)}
  function n(i){return typeof i==="number"?i+S.base:"?"}
  function col(c){return typeof c==="string"&&/^#[0-9a-fA-F]{6}$/.test(c)?c:null}
  function sw(c){return '<div class="sw'+(c?"":" empty")+'" style="'+(c?"background:"+c:"")+'"></div>'}
  function rgba(c,a){var v=rgb(c);return "rgba("+v[0]+","+v[1]+","+v[2]+","+a+")"}
  function spool(c,px){return '<div class="spool'+(c?"":" empty")+'" style="width:'+px+'px;height:'+px+'px;'+(c?"--c:"+c+";box-shadow:0 0 0 2px rgba(255,255,255,.10),0 0 12px "+rgba(c,.45):"")+'"></div>'}
  function rgb(h){var m=/^#?([0-9a-fA-F]{6})/.exec(String(h||""));h=m?m[1]:"777777";return [parseInt(h.slice(0,2),16),parseInt(h.slice(2,4),16),parseInt(h.slice(4,6),16)]}
  function cname(h){
    var c=rgb(h),r=c[0]/255,g=c[1]/255,b=c[2]/255,mx=Math.max(r,g,b),mn=Math.min(r,g,b),l=(mx+mn)/2,d=mx-mn,s=0,hu=0;
    if(d>0){s=d/(1-Math.abs(2*l-1));hu=mx===r?((g-b)/d)%6:mx===g?(b-r)/d+2:(r-g)/d+4;hu=(hu*60+360)%360}
    if(l>0.9)return "Blanc";if(l<0.1)return "Noir";
    if(s<0.15)return l>0.7?"Gris clair":l<0.32?"Gris foncé":"Gris";
    if(hu<12||hu>=345)return l<0.3?"Bordeaux":l>0.75?"Rose":"Rouge";
    if(hu<42)return (l<0.45||s<0.45)?(l>0.6?"Beige":"Marron"):(l>0.75?"Pêche":"Orange");
    if(hu<66)return l<0.35?"Kaki":(s<0.5&&l>0.7?"Crème":"Jaune");
    if(hu<160)return l<0.28?"Vert foncé":l>0.7?"Vert clair":"Vert";
    if(hu<195)return l>0.7?"Cyan clair":"Turquoise";
    if(hu<250)return l<0.3?"Bleu foncé":l>0.7?"Bleu clair":"Bleu";
    if(hu<290)return l>0.7?"Lavande":"Violet";
    return (s>0.6&&l<0.55)?"Magenta":"Rose";
  }

  function say(t,k){var m=$("msg");if(!t){m.className="msg";return}m.textContent=t;m.className="msg show "+(k||"info")}
  function word(x){return {empty:"vide",ready:"prête",loading:"chargement",unloading:"déchargement",error:"erreur",feeding:"alimentation",assist:"assistance",nosensor:"sans capteur",unknown:"inconnu"}[x]||x||""}
  function dis(){return S.locked?" disabled":""}
  function renderQueue(q){var box=$("queue");S.q=q;
    if(!q||!q.items.length){box.className="queue";box.innerHTML="";return}
    box.className="queue show";
    box.innerHTML='<b>File d’attente</b>'+(q.paused?' <span class="badge" style="color:var(--bad)">en pause</span>':'')+
      '<ol>'+q.items.map(function(it){var cls=it.status==="en cours"?"run":it.status==="échec"?"fail":"";
        return '<li class="'+cls+'">'+esc(it.label)+' <small>('+esc(it.status)+')</small>'+(it.status!=="en cours"?'<button class="x" data-q="'+it.id+'" title="Retirer">✕</button>':'')+'</li>'}).join("")+'</ol>'+
      (q.paused?'<button class="qb go" data-qa="queue_resume">Reprendre</button>':'')+
      (q.items.some(function(it){return it.status!=="en cours"})?'<button class="qb ghost" data-qa="queue_clear">Vider la file</button>':'')}
  document.addEventListener("click",function(e){var t=e.target;
    if(t.dataset&&t.dataset.q){post({command:"queue_remove",id:+t.dataset.q});e.stopPropagation();return}
    if(t.dataset&&t.dataset.qa){post({command:t.dataset.qa});e.stopPropagation()}},true);

  function spoolOf(st,ace,slot){var b=st.spool_binding||{},id=b[ace+"_"+slot];return id!=null?(st.spools||{})[String(id)]||null:null}
  function qty(sp,c){
    if(!sp)return "";
    var w=Number(sp.weight_g);
    if(w>0)return '<span class="qty">≈ '+Math.round(w)+' g</span><div class="bar"><i style="width:'+Math.min(100,Math.round(w/10))+'%'+(c?";background:linear-gradient(90deg,"+rgba(c,.55)+","+c+")":"")+'"></i></div>';
    var u=Number(sp.used_mm);
    if(u>0)return '<span class="qty">'+(u/1000).toFixed(1).replace(".",",")+' m utilisés</span>';
    return "";
  }
  function dryer(a){
    var d=a.dryer||{},st=String(d.status||"stop").toLowerCase(),on=st!=="stop"&&st!=="free"&&st!=="";
    if(on){
      // remain_time est en secondes (l'interface multiACE affiche remain_time/60 min).
      var r=Math.round((Number(d.remain_time)||0)/60),h=Math.floor(r/60),m=r%60;
      var tot=Number(d.duration)||0,pc=tot>0?Math.max(0,Math.min(100,Math.round(100-100*r/tot))):null;
      return '<div class="dry on"><b>🔥 Séchage '+(d.target_temp?d.target_temp+' °C':'')+'</b>'+(r?' · reste '+(h?h+' h ':'')+m+' min':'')+
        '<span style="flex:1"></span><button data-act="stopdry" data-ace="'+a.idx+'">Arrêter</button>'+
        (pc!=null?'<div class="dprog" title="'+pc+' %"><i style="width:'+pc+'%"></i></div>':'')+'</div>';
    }
    var t=S.dt[a.idx]||45,du=S.dd[a.idx]||240;
    var temps=[40,45,50,55].map(function(v){return '<option'+(v===t?" selected":"")+'>'+v+'</option>'}).join("");
    var durs=[[60,"1 h"],[120,"2 h"],[240,"4 h"],[360,"6 h"],[480,"8 h"]].map(function(v){return '<option value="'+v[0]+'"'+(v[0]===du?" selected":"")+'>'+v[1]+'</option>'}).join("");
    return '<div class="dry">Séchage <select data-dt="'+a.idx+'">'+temps+'</select>°C <select data-dd="'+a.idx+'">'+durs+'</select>'+
      '<span style="flex:1"></span><button class="go" data-act="dry" data-ace="'+a.idx+'">Sécher</button></div>';
  }
  var MATS=["PLA","PETG","ABS","ASA","TPU","PA","PC","PLA-CF","PETG-CF","PA-CF"];
  var QUICK=["#ffffff","#000000","#808080","#e53935","#fb8c00","#fdd835","#43a047","#1e88e5","#8e24aa","#f48fb1","#8d6e63","#c0a080"];
  function editor(st,a,s){
    var sp=spoolOf(st,a.idx,s.idx),c=col(s.color)||"#ffffff",mat=(s.material||"PLA").toUpperCase();
    var opts=MATS.indexOf(mat)<0?[mat].concat(MATS):MATS;
    var w=sp&&Number(sp.weight_g)>0?Math.round(sp.weight_g):"";
    var cur=sp?String(sp.id):"";
    var all=Object.keys(st.spools||{}).map(function(k){return st.spools[k]}).sort(function(x,y){return Number(x.id)-Number(y.id)});
    // Liste maison (pas un <select>) : pastille de couleur, texte lisible sur fond sombre, et l'endroit
    // ou la bobine est deja montee.
    var where={};Object.keys(st.spool_binding||{}).forEach(function(k){var v=String(st.spool_binding[k]);var m=/^(\d+)_(\d+)$/.exec(k);if(m)where[v]="ACE "+n(+m[1])+" · slot "+n(+m[2])});
    var spLab=function(x){return "#"+x.id+" "+[x.label,x.vendor,x.material,x.subtype].filter(Boolean).join(" ")};
    var spRow=function(x){var id=String(x.id),w2=Number(x.weight_g)>0?Math.round(x.weight_g)+" g":"",here=id===cur;
      return '<div class="spo'+(here?" on":"")+'" data-v="'+esc(id)+'" data-w="'+(Number(x.weight_g)>0?Math.round(x.weight_g):"")+'">'+sw(col("#"+(x.color||""))||"#888")+
        '<span class="spl">'+esc(spLab(x))+'<small>'+esc(cname("#"+(x.color||"")))+(w2?" · "+w2:"")+(where[id]&&!here?" · sur "+where[id]:"")+'</small></span></div>'};
    var curSp=cur&&st.spools?st.spools[cur]:null;
    var spoolLine='<label>Bobine</label><div class="sppick" style="grid-column:auto"><input type="hidden" id="e_spid" value="'+esc(cur)+'">'+
        '<button type="button" class="spbtn" id="e_spbtn" title="Bobine de la table multiACE associée à ce slot (utile sans RFID : poids, calibration PA mémorisée)">'+
        (curSp?sw(col("#"+(curSp.color||"")))+esc(spLab(curSp)):"Aucune")+' ▾</button>'+
        '<div class="splist" id="e_splist"><div class="spo" data-v="">Aucune (détacher)</div>'+all.map(spRow).join("")+'<div class="spo new" data-v="new">+ Nouvelle bobine</div></div></div>'+
      '<label>Poids</label><div class="full" style="grid-column:auto"><input id="e_w" type="number" min="0" max="65535" step="1" value="'+w+'" style="width:80px"> g restants</div>'+
      (sp?'<div class="full"><label><input id="e_sp" type="checkbox" checked> appliquer couleur / matière à la bobine '+esc(sp.label||("#"+sp.id))+'</label></div>':'')+
      (sp&&sp.pa_matrix&&Object.keys(sp.pa_matrix).length?'<div class="full note">PA mémorisé : '+Object.keys(sp.pa_matrix).map(function(k){return esc(k.replace("_"," mm ").replace("high_flow","haut débit").replace("standard","standard"))+" = "+Number(sp.pa_matrix[k]).toFixed(4)}).join(" · ")+'</div>':
        '<div class="full note">'+(sp?'Pas encore de PA mémorisé pour cette bobine.':'Associe une bobine pour mémoriser le poids et la calibration PA.')+'</div>');
    var hh=headFor(st,a.idx,s.idx);
    var paBtn=hh==null?"":'<button data-act="calpa" data-head="'+hh+'" data-ace="'+a.idx+'" data-slot="'+s.idx+'"'+(sp?dis():" disabled")+' title="Charge cette bobine sur T'+n(hh)+' si besoin, puis mesure son PA (FLOW_CALIBRATE) et le mémorise sur la bobine pour cette buse">Calibrer cette bobine (PA)</button>';
    return '<div class="ed" data-ace="'+a.idx+'" data-slot="'+s.idx+'">'+
      '<label>Couleur</label><div class="full" style="grid-column:auto"><input id="e_c" type="color" value="'+c+'"><input id="e_hex" value="'+c+'" style="width:76px"></div>'+
      '<div class="full sw2">'+QUICK.map(function(q){return '<i data-q="'+q+'" style="background:'+q+'"></i>'}).join("")+'</div>'+
      '<label>Matière</label><select id="e_m">'+opts.map(function(o){return '<option'+(o===mat?" selected":"")+'>'+esc(o)+'</option>'}).join("")+'</select>'+
      '<label>Marque</label><input id="e_b" value="'+esc(s.brand||"")+'" placeholder="ex. SUNLU">'+
      '<label>Type</label><input id="e_s" value="'+esc(s.subtype||"")+'" placeholder="ex. Basic, Matte, Silk">'+
      spoolLine+
      '<div class="full"><button class="go" id="e_ok">Enregistrer</button><button id="e_no">Annuler</button>'+
      (s.source==="override"?'<button id="e_rf" title="Supprime la saisie manuelle">Revenir au RFID</button>':'')+'</div>'+
      (paBtn?'<div class="full">'+paBtn+'</div>':'')+'</div>';
  }
  function headFor(st,ace,slot){
    if(st.mode==="head"){var ha=st.head_ace||{};for(var h in ha){if(Number(ha[h])===ace)return Number(h)}return null}
    return slot;
  }
  // Etat des tetes APRES la file d'attente : les boutons se calculent dessus, pour preparer une
  // sequence complete d'avance et ne pas proposer deux fois la meme action.
  function planned(st){
    var hs=(st.toolheads||[]).map(function(t){return {idx:t.idx,filament_detected:!!t.filament_detected,ace:t.ace,slot:t.slot,manual:t.manual,feeder:t.feeder}});
    ((S.q&&S.q.items)||[]).forEach(function(it){var a=it.args||{},h=+a.HEAD;
      if(it.name==="ACE_LOAD_HEAD"||it.name==="ACE_SWAP_HEAD"){if(hs[h]){hs[h].filament_detected=true;hs[h].ace=+a.ACE;hs[h].slot=+a.SLOT}}
      else if(it.name==="ACE_UNLOAD_HEAD"){if(hs[h]){hs[h].filament_detected=false;hs[h].ace=null;hs[h].slot=null}}
      else if(it.name==="ACE_UNLOAD_ALL_HEADS"){hs.forEach(function(x){if(!x.manual&&!x.feeder){x.filament_detected=false;x.ace=null;x.slot=null}})}});
    return hs}
  function slotName(st,a,s){var A=(st.aces||[]).filter(function(x){return x.idx===a})[0];var sl=A&&(A.slots||[]).filter(function(x){return x.idx===s})[0];
    return sl?{c:col(sl.color),txt:"ACE "+n(a)+" · slot "+n(s)}:{c:null,txt:"ACE "+n(a)+" · slot "+n(s)}}
  function renderPrep(p){
    var el=$("prep");if(!el)return;
    S.prep=p;if(S.last)renderMini(S.last);
    if(!p){el.innerHTML="";return}
    var ae=document.activeElement;if(ae&&ae.closest&&ae.closest("#prep")&&ae.tagName==="SELECT")return;
    S.prepOpen=S.prepOpen||{};
    var real=p.real||["","","",""],man=p.manual||real;
    var sel='<div class="rn">'+man.map(function(v,h){return '<label>T'+(h+1)+' <select data-rn="'+h+'"><option value=""'+(v?"":" selected")+'>?</option>'+
      ["Standard","Haut débit"].map(function(o){return '<option'+(v===o?" selected":"")+'>'+o+'</option>'}).join("")+'</select></label>'}).join("")+'</div>';
    function fold(k,title,body,open){var o=S.prepOpen[k];if(o===undefined)o=!!open;
      return '<details class="pf" data-k="'+k+'"'+(o?" open":"")+'><summary>'+title+'</summary>'+body+'</details>'}
    var html;
    if(!p.real_known){
      html='<div class="note">Indique une seule fois la buse vissée sur chaque tête de ta U1 :</div>'+sel;
    }else{
      var todo={};p.todo.forEach(function(t){todo[t.t]=t.need});
      var cell=function(i){var r=p.rows[i]||{},v=todo[i]||(r.found&&r.need)||r.now||"?",chg=todo[i]!=null;
        return '<div class="nc'+(chg?" chg":"")+'">T'+(i+1)+' '+esc(chg?v.toUpperCase():v)+(chg?" ←":"")+'</div>'};
      var warn=(p.shared||[]).map(function(x){return '<div class="pw">⚠ Filaments '+x.filaments.map(function(t){return t+1}).join(" et ")+' sur la même tête T'+(x.head+1)+' : échanges de bobine pendant l’impression.</div>'}).join("")+
        p.rows.filter(function(r){return !r.found}).map(function(r){return '<div class="pw">⚠ Filament '+(r.t+1)+' ('+esc(cname(r.color))+') : aucune bobine de cette couleur dans les ACE.</div>'}).join("")+
        (p.extra?'<div class="note">'+p.extra+' filament(s) au-delà du 4e : non vérifié(s).</div>':'');
      var head=p.todo.length?'<div class="ph pw">⚠ Mets ça à gauche (Imprimante → Buse) puis tranche :</div><div class="ng">'+[0,1,2,3].map(cell).join("")+'</div>':
        '<div class="ph pok">✓ buses d’OrcaSlicer OK pour tes bobines</div>';
      var rows=p.rows.map(function(r){
          var where=r.found?'ACE '+n(r.ace)+' slot '+n(r.slot)+' → T'+(r.head+1)+' · '+esc(r.need||"?")+(r.ok?' <span class="okc">✓</span>':''):'<span class="warnc">pas dans les ACE</span>';
          return '<div class="pr">'+sw(col(r.color))+'<span><b>Filament '+(r.t+1)+'</b> '+esc(cname(r.color))+' → '+where+'</span></div>'}).join("")+
        '<div class="note">Pour OrcaSlicer, le filament N part sur TN ; en vrai, il part sur la tête du slot de sa bobine.</div>';
      var mine=p.real_src==="u1"?'<div class="note">Lues dans la U1 : '+real.map(function(v,h){return 'T'+(h+1)+' '+esc(v)}).join(" · ")+'. Rien à saisir.</div>':
        (p.real_src==="mixte"?'<div class="note">En partie lues dans la U1 ; le reste vient de ta saisie :</div>'+sel:
         '<div class="note">La U1 ne donne pas ses buses (firmware ancien) : ta saisie est utilisée.</div>'+sel);
      html=head+warn+fold("d","Détail par filament",rows,false)+fold("u","Ma U1 (buses vissées)"+(p.real_src==="u1"?" · lues dans la U1":""),mine,false);
    }
    var mv='<button class="pmv" data-pmv="1" title="Déplacer cette carte">'+(S.prepPos==="bottom"?"↑ en haut":"↓ en bas")+'</button>';
    var pf=isF("prep"),stat=!p.real_known?"":(p.todo.length?' <span class="warnc">· à régler</span>':' <span class="okc">· ✓</span>');
    el.innerHTML='<div class="prep'+(pf?" folded":"")+'">'+mv+'<div class="ptitle" data-fold="prep"><i class="chev">▾</i>Avant de trancher'+stat+'</div><div class="pbody">'+html+'</div></div>';
    el.querySelector("[data-pmv]").onclick=function(){S.prepPos=S.prepPos==="bottom"?"top":"bottom";placePrep();post({command:"prefs_set",prep_pos:S.prepPos});renderPrep(S.prep)};
    Array.prototype.forEach.call(el.querySelectorAll("details.pf"),function(d){d.addEventListener("toggle",function(){S.prepOpen[d.dataset.k]=d.open})});
    Array.prototype.forEach.call(el.querySelectorAll("select[data-rn]"),function(x){x.onchange=function(){
      var v=[0,1,2,3].map(function(h){var s=el.querySelector('select[data-rn="'+h+'"]');return s?s.value:""});
      post({command:"prefs_set",real_nozzles:v});x.blur();setTimeout(function(){post({command:"refresh"})},150)}});
  }
  function render(st){
    S.last=st;renderMini(st);applyFold();
    $("headsMini").innerHTML=isF("heads")?minis((st.toolheads||[]).map(function(t){return t.filament_detected?col(t.color):null}),(st.toolheads||[]).map(function(t){return "h:"+t.idx})):"";
    S.base=st.display_index_base===0?0:1;
    var ps=(st.printer_state||"").toLowerCase();
    // Pendant un echange multiACE on peut continuer a remplir la file : seule l'impression bloque.
    S.locked=ps==="printing"||ps==="paused";
    var label=(S.q&&S.q.items.some(function(i){return i.status==="en cours"}))?"action en cours":ps==="printing"?"impression":ps==="paused"?"en pause":st.swap_in_progress?"échange en cours":"prête";
    $("st").className="pill "+(label!=="prête"?"warn":"ok");$("st").textContent=label;
    var heads=st.toolheads||[],ph=planned(st),qn=(S.q&&S.q.items||[]).length;
    $("heads").innerHTML=heads.map(function(t){
      var loaded=!!t.filament_detected,c=loaded?col(t.color):null;
      var src=t.manual?"manuel":t.feeder?"chargeur U1":(t.ace!=null&&t.slot!=null)?("ACE "+n(t.ace)+" · slot "+n(t.slot)):(loaded?"source inconnue":"vide");
      var fail=t.load_failed?' <span class="badge" style="color:var(--bad)">échec</span>':"";
      var p=ph[t.idx]||t,pl=!!p.filament_detected;
      var can=pl&&!t.manual&&!t.feeder;
      var changed=qn&&(pl!==loaded||(pl&&(p.ace!==t.ace||p.slot!==t.slot)));
      var plan=changed?'<small class="plan">après la file : '+(pl?(p.ace!=null?esc(slotName(st,p.ace,p.slot).txt):"chargée"):"vide")+'</small>':"";
      return '<div class="htile'+(loaded?" on":"")+'"'+(c?' style="--tint:'+rgba(c,.22)+'"':"")+'><div class="hrow">'+spool(c,28)+
        '<div><div class="hn">T'+n(t.idx)+'</div><div class="hm">'+esc(loaded?(t.material||"chargée")+(t.subtype?" "+t.subtype:""):"vide")+fail+'</div></div></div>'+
        '<small>'+esc(src)+'</small>'+plan+
        (can?'<button data-act="unload" data-head="'+t.idx+'"'+dis()+'>Décharger</button>':"")+'</div>';
    }).join("")||'<div class="note">—</div>';
    Array.prototype.forEach.call(document.querySelectorAll('button[data-act=calbed]'),function(x){x.disabled=S.locked});
    $("ua").disabled=S.locked||!ph.some(function(t){return t.filament_detected&&!t.manual&&!t.feeder});
    $("aces").innerHTML=(st.aces||[]).map(function(a){
      var fk="ace"+a.idx,fo=isF(fk),dd=a.dryer||{},dso=String(dd.status||"stop").toLowerCase(),don=dso!=="stop"&&dso!=="free"&&dso!=="";
      var mini=fo?'<span class="fmini">'+minis((a.slots||[]).map(function(s){return s.state==="empty"||s.source==="empty"?null:col(s.color)}),(a.slots||[]).map(function(s){return "s:"+a.idx+":"+s.idx}))+'</span>'+(don?' <span style="color:#f0a35a;text-transform:none;letter-spacing:0">🔥</span>':""):"";
      var head='<h4 class="fh" data-fold="'+fk+'"><span><i class="chev">▾</i>'+(a.unit_name?esc(a.unit_name):"ACE "+n(a.idx))+mini+(a.connected?"":' <span class="badge" style="color:var(--bad)">déconnecté</span>')+'</span>'+climate(a)+'</h4>';
      return '<div class="card ace'+(fo?" folded":"")+'">'+head+dryer(a)+(a.slots||[]).map(function(s){
        var empty=s.state==="empty"||s.source==="empty",c=empty?null:col(s.color);
        var h=headFor(st,a.idx,s.idx);
        var onHead=ph.some(function(t){return t.ace===a.idx&&t.slot===s.idx&&t.filament_detected});
        var onNow=heads.some(function(t){return t.ace===a.idx&&t.slot===s.idx&&t.filament_detected});
        var name=empty?"vide":esc((s.brand?s.brand+" ":"")+(s.material||"inconnu")+(s.subtype?" "+s.subtype:""));
        var badge=s.source==="derived"?' <span class="badge derived">déduit</span>':"";
        var busyHead=h!=null&&ph.some(function(t){return t.idx===h&&t.filament_detected});
        var act=busyHead?"swap":"load",verb=busyHead?"Échanger":"Charger";
        var btn=empty||h==null?"":onHead?'<span class="badge">'+(onNow?"sur":"prévue sur")+' T'+n(h)+'</span>':
          '<button class="go" data-act="'+act+'" data-head="'+h+'" data-ace="'+a.idx+'" data-slot="'+s.idx+'"'+dis()+'>'+verb+' → T'+n(h)+'</button>';
        var q=empty?"":qty(spoolOf(st,a.idx,s.idx),c);
        var editing=S.edit&&S.edit.ace===a.idx&&S.edit.slot===s.idx;
        return '<div class="item'+(empty?"":" click")+'" data-edit="'+(empty?"":a.idx+"_"+s.idx)+'" title="'+(empty?"":"Cliquer pour modifier couleur, matière, poids")+'">'+spool(c,22)+'<div class="t"><b>'+n(s.idx)+'</b> '+name+badge+'<small>'+(empty?"":esc(word(s.state)))+'</small>'+(q?'<small>'+q+'</small>':'')+'</div>'+btn+'</div>'+
          (editing?editor(st,a,s):"");
      }).join("")+'</div>';
    }).join("")||'<h4><span>ACE</span></h4><div class="note">Aucun ACE.</div>';
    rearm();
  }
  function keyOf(b){return b.id==="ua"?"ua":b.dataset.act+(b.dataset.head||"")+(b.dataset.ace||"")+(b.dataset.slot||"")}
  // Un rafraichissement ne doit pas annuler un bouton en attente de confirmation.
  function rearm(){if(!S.armed)return;var found=null;
    Array.prototype.forEach.call(document.querySelectorAll("button[data-act],#ua"),function(x){if(keyOf(x)===S.armed)found=x});
    if(!found||found.disabled){S.armed=null;return}
    found.dataset.label=found.textContent;found.classList.add("arm");found.textContent="Confirmer ?"}
  function closeEdit(){S.edit=null;if(S.last)render(S.last)}
  // ---- écran distant de la U1 (Extended Firmware : Paramètres > Firmware > Remote Screen)
  S.screen="off";S.compact=false;S.host="";S.shotBusy=false;
  function screenBox(){return S.screen==="top"?$("screenTop"):S.screen==="bottom"?$("screenBottom"):null}
  function placeScreen(){
    $("screenTop").innerHTML="";$("screenBottom").innerHTML="";
    $("scr").classList.toggle("on",S.screen!=="off");
    $("scr").title="Écran de la U1 : "+(S.screen==="off"?"masqué":S.screen==="top"?"en haut":"en bas")+" (clic pour changer)";
    var box=screenBox();if(!box||!S.host)return;
    box.innerHTML='<div class="screen"><img id="shot" alt="Écran de la U1" title="Clique pour toucher l’écran de la U1"></div>';
    S.shotBusy=false;nextShot();
  }
  function nextShot(){
    var img=$("shot");if(!img||S.shotBusy||document.hidden)return;
    S.shotBusy=true;
    var probe=new Image();
    probe.onload=function(){S.shotBusy=false;var i=$("shot");if(i){i.src=probe.src;i.dataset.w=probe.naturalWidth;i.dataset.h=probe.naturalHeight}};
    probe.onerror=function(){S.shotBusy=false;var b=screenBox();if(b&&$("shot"))b.innerHTML='<div class="screen"><div class="err">Écran distant indisponible.<br>Active <b>Remote Screen</b> dans Paramètres › Firmware de la U1 (firmware Extended).</div></div>';};
    probe.src="http://"+S.host+"/screen/snapshot?t="+Date.now();
  }
  setInterval(nextShot,700);
  // ---- camera de la U1 (Moonraker : webcam « case », image fixe /webcam/snapshot.jpg)
  S.cam="off";S.camBusy=false;
  function camBox(){return S.cam==="top"?$("camTop"):S.cam==="bottom"?$("camBottom"):null}
  function placeCam(){
    $("camTop").innerHTML="";$("camBottom").innerHTML="";
    $("cam").classList.toggle("on",S.cam!=="off");
    $("cam").title="Caméra de la U1 : "+(S.cam==="off"?"masquée":S.cam==="top"?"en haut":"en bas")+" (clic pour changer)";
    var box=camBox();if(!box||!S.host)return;
    box.innerHTML='<div class="cam"><img id="camimg" alt="Caméra de la U1"><span class="live">● LIVE</span></div>';
    S.camBusy=false;nextCam();
  }
  function nextCam(){
    var img=$("camimg");if(!img||S.camBusy||document.hidden)return;
    S.camBusy=true;
    var probe=new Image();
    probe.onload=function(){S.camBusy=false;var i=$("camimg");if(i)i.src=probe.src};
    probe.onerror=function(){S.camBusy=false;var b=camBox();if(b&&$("camimg"))b.innerHTML='<div class="cam"><div class="err">Caméra indisponible pour le moment.</div></div>'};
    probe.src="http://"+S.host+"/webcam/snapshot.jpg?t="+Date.now();
  }
  setInterval(nextCam,1000);
  S.fold={};
  function isF(k){return !!S.fold[k]}
  function climate(a){var h=a.humidity_effective!=null?a.humidity_effective:a.humidity,t=Number(a.temp),out="";
    if(typeof h==="number")out+='<span class="hum '+(h<30?"ok":h<45?"mid":"hi")+'" title="Humidité dans l’ACE">💧 '+Math.round(h)+' %</span>';
    if(a.temp!=null&&a.temp!==""&&isFinite(t))out+=' <span class="hum tmp" title="Température dans l’ACE">🌡 '+Math.round(t)+' °C</span>';
    return out}
  function minis(list,keys){return list.map(function(c,i){return keys?'<span data-pk="'+keys[i]+'">'+spool(c,13)+'</span>':spool(c,13)}).join("")}
  function applyFold(){var hc=$("headsCard");if(hc)hc.classList.toggle("folded",isF("heads"))}
  document.addEventListener("click",function(e){
    var h=e.target.closest&&e.target.closest("[data-fold]");if(!h||e.target.closest("button,select,input,a,[data-pk]"))return;
    var k=h.dataset.fold;S.fold[k]=!isF(k);post({command:"prefs_set",fold:{k:k,on:S.fold[k]}});
    applyFold();if(S.last)render(S.last);renderPrep(S.prep)});
  function closePop(){var o=$("pop");if(o)o.remove()}
  function popFor(pk){
    var st=S.last||{},f=pk.split(":"),k=f[0],heads=st.toolheads||[],ph=planned(st),html="";
    if(k==="h"){var t=heads.filter(function(x){return x.idx===+f[1]})[0];if(!t)return "";
      var c=t.filament_detected?col(t.color):null,src=t.ace!=null&&t.slot!=null?"ACE "+n(t.ace)+" · slot "+n(t.slot):(t.filament_detected?"source inconnue":"vide");
      var p=ph[t.idx]||t;
      html='<div class="pt">'+spool(c,22)+'<div>T'+n(t.idx)+' · '+esc(t.filament_detected?(t.material||"chargée"):"vide")+'<small>'+esc(src)+'</small></div></div>'+
        (p.filament_detected&&!t.manual&&!t.feeder?'<button data-act="unload" data-head="'+t.idx+'"'+dis()+'>Décharger T'+n(t.idx)+'</button>':'<div class="pn">Rien à faire sur cette tête.</div>');
    }else if(k==="s"){var a=(st.aces||[]).filter(function(x){return x.idx===+f[1]})[0],sl=a&&(a.slots||[]).filter(function(x){return x.idx===+f[2]})[0];if(!sl)return "";
      var empty=sl.state==="empty"||sl.source==="empty",c=empty?null:col(sl.color),hh=headFor(st,a.idx,sl.idx);
      var on=ph.filter(function(x){return x.ace===a.idx&&x.slot===sl.idx&&x.filament_detected})[0];
      var busy=hh!=null&&ph.some(function(x){return x.idx===hh&&x.filament_detected});
      html='<div class="pt">'+spool(c,22)+'<div>'+(empty?"Slot "+n(sl.idx)+" vide":esc((sl.brand?sl.brand+" ":"")+(sl.material||""))+' <span style="color:var(--muted)">'+esc(cname(sl.color))+'</span>')+'<small>ACE '+n(a.idx)+' · slot '+n(sl.idx)+'</small></div></div>';
      if(!empty){
        html+=on?'<button data-act="unload" data-head="'+on.idx+'"'+dis()+'>Décharger T'+n(on.idx)+'</button>':
          (hh!=null?'<button class="go" data-act="'+(busy?"swap":"load")+'" data-head="'+hh+'" data-ace="'+a.idx+'" data-slot="'+sl.idx+'"'+dis()+'>'+(busy?"Échanger":"Charger")+' → T'+n(hh)+'</button>':"");
        html+='<button data-pedit="'+a.idx+'_'+sl.idx+'">Modifier couleur / matière / poids…</button>';
      }else html+='<div class="pn">Mets une bobine dans ce slot pour l’utiliser.</div>';
    }else if(k==="a"){var A=(st.aces||[]).filter(function(x){return x.idx===+f[1]})[0];if(!A)return "";
      var d=A.dryer||{},ds=String(d.status||"stop").toLowerCase(),don=ds!=="stop"&&ds!=="free"&&ds!=="",r=Math.round((Number(d.remain_time)||0)/60);
      html='<div class="pt">'+(A.unit_name?esc(A.unit_name):"ACE "+n(A.idx))+'</div><div class="pn">'+climate(A)+'</div>'+
        (don?'<div class="pn">🔥 Séchage '+(d.target_temp||"")+' °C'+(r?' · reste '+(Math.floor(r/60)?Math.floor(r/60)+' h ':'')+r%60+' min':'')+'</div><button data-act="stopdry" data-ace="'+A.idx+'">Arrêter le séchage</button>':
          '<button class="go" data-act="dry" data-ace="'+A.idx+'">Sécher '+(S.dt[A.idx]||45)+' °C · '+((S.dd[A.idx]||240)/60)+' h</button><div class="pn">Température et durée : dans le panneau complet.</div>');
    }
    return html;
  }
  document.addEventListener("click",function(e){
    var pb=e.target.closest&&e.target.closest("[data-pedit]");
    if(pb){var q=pb.dataset.pedit.split("_");closePop();S.edit={ace:+q[0],slot:+q[1]};
      if(S.compact){setCompact(false);savePrefs()}
      if(isF("ace"+q[0])){S.fold["ace"+q[0]]=false;post({command:"prefs_set",fold:{k:"ace"+q[0],on:false}})}
      if(S.last)render(S.last);return}
    var t=e.target.closest&&e.target.closest("[data-pk]");
    if(!t){if(!(e.target.closest&&e.target.closest(".pop")))closePop();return}
    closePop();var html=popFor(t.dataset.pk);if(!html)return;
    var o=document.createElement("div");o.id="pop";o.className="pop";o.innerHTML=html;document.body.appendChild(o);
    var r=t.getBoundingClientRect(),w=o.offsetWidth,h=o.offsetHeight;
    o.style.left=Math.max(6,Math.min(window.innerWidth-w-6,r.left+r.width/2-w/2))+"px";
    o.style.top=(r.bottom+6+h>window.innerHeight?Math.max(6,r.top-h-6):r.bottom+6)+"px";
  },true);
  document.addEventListener("keydown",function(e){if(e.key==="Escape")closePop()});
  function placePrep(){var el=$("prep");if(!el)return;($(S.prepPos==="bottom"?"prepBottom":"prepTop")).appendChild(el)}
  function setCompact(on){
    S.compact=on;document.body.classList.toggle("compact",on);
    $("full").hidden=on;$("mini").hidden=!on;$("cmp").textContent=on?"+":"–";$("cmp").title=on?"Agrandir":"Réduire";
  }
  function renderMini(st){
    var heads=st.toolheads||[],on=function(a,sl){return heads.filter(function(t){return t.filament_detected&&t.ace===a&&t.slot===sl})[0]};
    var p=S.prep,pr="";
    if(p&&p.real_known)pr=p.todo&&p.todo.length?'<div class="mprep todo">⚠ Buses à régler dans OrcaSlicer : '+p.todo.map(function(t){return "T"+(t.t+1)+" "+esc(t.need)}).join(" · ")+'</div>':
      '<div class="mprep ok">✓ Buses OK pour tes bobines</div>';
    var hr='<div class="mrow"><span class="lab">Têtes</span>'+heads.map(function(t){var c=t.filament_detected?col(t.color):null;
      return '<div class="sl" data-pk="h:'+t.idx+'" title="'+esc(t.filament_detected?(t.material||"chargée"):"vide")+'">'+spool(c,20)+'<small class="on">T'+n(t.idx)+'</small></div>'}).join("")+'</div>';
    var ar=(st.aces||[]).map(function(a){
      var d=a.dryer||{},dst=String(d.status||"stop").toLowerCase(),dr=dst!=="stop"&&dst!=="free"&&dst!=="";
      var rm=Math.round((Number(d.remain_time)||0)/60),rt=rm?(Math.floor(rm/60)?Math.floor(rm/60)+" h ":"")+(rm%60)+" min":"";
      var slots=(a.slots||[]).map(function(s){var empty=s.state==="empty"||s.source==="empty",c=empty?null:col(s.color),t=empty?null:on(a.idx,s.idx);
        return '<div class="sl" data-pk="s:'+a.idx+':'+s.idx+'" title="'+esc(empty?"vide":(s.brand?s.brand+" ":"")+(s.material||""))+'">'+spool(c,20)+'<small'+(t?' class="on">T'+n(t.idx):'>'+n(s.idx))+'</small></div>'}).join("");
      return '<div class="mrow"><span class="lab" data-pk="a:'+a.idx+'" title="Séchage">'+(a.unit_name?esc(a.unit_name):"ACE "+n(a.idx))+(a.connected===false?' <span style="color:var(--bad)">✕</span>':"")+'</span>'+slots+
        '<div class="info"><span>'+climate(a)+'</span>'+(dr?'<span>🔥 '+(d.target_temp||"")+'°'+(rt?" · "+rt:"")+'</span>':"")+'</div></div>';
    }).join("");
    $("mini").innerHTML=pr+hr+ar;
  }
  function savePrefs(){post({command:"prefs_set",screen:S.screen,camera:S.cam,compact:S.compact})}
  $("cam").onclick=function(){S.cam=S.cam==="off"?"top":S.cam==="top"?"bottom":"off";placeCam();savePrefs()};
  $("scr").onclick=function(){S.screen=S.screen==="off"?"top":S.screen==="top"?"bottom":"off";placeScreen();savePrefs()};
  $("cmp").onclick=function(){setCompact(!S.compact);savePrefs()};
  $("hd").onclick=function(){post({command:"hide"})};

  document.addEventListener("click",function(e){
    var img=e.target;if(img.id!=="shot"||!img.dataset.w)return;
    var r=img.getBoundingClientRect(),x=Math.round((e.clientX-r.left)*img.dataset.w/r.width),y=Math.round((e.clientY-r.top)*img.dataset.h/r.height);
    post({command:"tap",x:x,y:y});setTimeout(nextShot,250);
  });
  document.addEventListener("click",function(e){
    var t=e.target;
    if(t.dataset&&t.dataset.q){$("e_c").value=t.dataset.q;$("e_hex").value=t.dataset.q;return}
    if(t.id==="e_no"){closeEdit();return}
    if(t.id==="e_rf"){var ed=t.closest(".ed");post({command:"reset",ace:+ed.dataset.ace,slot:+ed.dataset.slot});S.busy=true;say("Envoi…","info");S.edit=null;return}
    if(t.id==="e_ok"){
      var ed2=t.closest(".ed"),hex=$("e_hex").value.trim();
      if(!/^#[0-9a-fA-F]{6}$/.test(hex)){say("Couleur invalide (format #RRGGBB).","err");return}
      var wEl=$("e_w"),spEl=$("e_sp"),sid=$("e_spid");
      post({command:"edit",ace:+ed2.dataset.ace,slot:+ed2.dataset.slot,color:hex,material:$("e_m").value,
            brand:$("e_b").value,subtype:$("e_s").value,weight:wEl?wEl.value:"",apply_spool:spEl?spEl.checked:false,
            spool:sid?sid.value:null});
      S.busy=true;S.edit=null;say("Enregistrement…","info");return;
    }
    if(t.closest("#e_spbtn")){var L=$("e_splist");L.classList.toggle("show");return}
    var o=t.closest(".spo");
    if(o&&o.closest("#e_splist")){var v=o.dataset.v;$("e_spid").value=v;$("e_splist").classList.remove("show");
      $("e_spbtn").innerHTML=(v==="new"?"+ Nouvelle bobine":v===""?"Aucune":o.innerHTML.replace(/<small>.*<\/small>/,""))+" ▾";
      if(v&&v!=="new"){
        if($("e_w"))$("e_w").value=o.dataset.w||"";
        // La bobine choisie impose son identite au slot : couleur, matiere, marque, type.
        var spx=(S.last&&S.last.spools||{})[v];
        if(spx){var hx=col("#"+(spx.color||""));if(hx){hx=hx.toLowerCase();$("e_c").value=hx;$("e_hex").value=hx}
          var mt=String(spx.material||"").toUpperCase();if(mt){var sel=$("e_m");if(!Array.prototype.some.call(sel.options,function(x){return x.value===mt})){var op=document.createElement("option");op.textContent=mt;sel.insertBefore(op,sel.firstChild)}sel.value=mt}
          $("e_b").value=spx.vendor||"";$("e_s").value=spx.subtype||"";
          var cb=$("e_sp");if(cb)cb.checked=false}}
      if(v==="new"&&$("e_w"))$("e_w").value="1000";
      return}
    if(t.closest(".ed")&&!t.closest("button[data-act]"))return;
    var row=t.closest(".item.click");
    if(row&&!t.closest("button")&&row.dataset.edit){
      var p=row.dataset.edit.split("_");S.edit={ace:+p[0],slot:+p[1]};if(S.last)render(S.last);return;
    }
    var b=e.target.closest("button[data-act]")||(e.target.id==="ua"?e.target:null);
    if(!b||b.disabled)return;
    var key=keyOf(b);
    if(S.armed!==key){
      Array.prototype.forEach.call(document.querySelectorAll("button.arm"),function(x){x.classList.remove("arm");x.textContent=x.dataset.label||x.textContent});
      S.armed=key;b.dataset.label=b.textContent;b.classList.add("arm");b.textContent="Confirmer ?";
      clearTimeout(S.armT);S.armT=setTimeout(function(){if(S.armed===key){S.armed=null;if(S.last&&!S.edit)render(S.last)}},6000);
      return;
    }
    S.armed=null;clearTimeout(S.armT);
    var queued=b.id==="ua"||["unload","load","swap","dry","calpa","calbed"].indexOf(b.dataset.act)>=0;
    if(!queued)S.busy=true;
    if(b.id==="ua")post({command:"unload_all"});
    else if(b.dataset.act==="unload")post({command:"unload",head:+b.dataset.head});
    else if(b.dataset.act==="dry"){var ai=+b.dataset.ace;post({command:"dry",ace:ai,temp:S.dt[ai]||45,duration:S.dd[ai]||240})}
    else if(b.dataset.act==="stopdry")post({command:"stopdry",ace:+b.dataset.ace});
    else if(b.dataset.act==="calpa"){post({command:"calib_pa",head:+b.dataset.head,ace:+b.dataset.ace,slot:+b.dataset.slot});S.edit=null}
    else if(b.dataset.act==="calbed")post({command:"calib_bed",temp:S.bt||55});
    else post({command:b.dataset.act,head:+b.dataset.head,ace:+b.dataset.ace,slot:+b.dataset.slot});
    if(b.closest(".pop"))setTimeout(closePop,0);
    if(queued){say("Ajouté à la file d’attente : tu peux en ajouter d’autres.","info");b.textContent=b.dataset.label||b.textContent;b.classList.remove("arm");return}
    say("Commande envoyée à la U1…","info");
  });
  document.addEventListener("input",function(e){
    var t=e.target;
    if(t.id==="e_c")$("e_hex").value=t.value;
    if(t.id==="e_hex"&&/^#[0-9a-fA-F]{6}$/.test(t.value.trim()))$("e_c").value=t.value.trim();
  });
  document.addEventListener("change",function(e){
    var t=e.target;if(t.id==="bt")S.bt=+t.value;
    if(t.dataset.dt!=null)S.dt[t.dataset.dt]=+t.value;if(t.dataset.dd!=null)S.dd[t.dataset.dd]=+t.value;
  });
  $("rf").onclick=function(){post({command:"refresh"})};
  function hostBox(show,title){var b=$("hostbox");b.hidden=!show;S.hostEditing=!!show&&!!title&&title!=="Adresse de la U1 introuvable";$("hostTitle").textContent=title||"Adresse de la U1 introuvable";if(show){var i=$("hostIn");if(!i.value)i.value=S.host||"";}}
  $("hostOk").onclick=function(){var v=$("hostIn").value.trim();if(!v){$("hostIn").focus();return}$("hostOk").disabled=true;post({command:"set_host",host:v})};
  $("hostIn").onkeydown=function(e){if(e.key==="Enter")$("hostOk").onclick()};
  $("hostX").onclick=function(){S.hostEditing=false;$("hostbox").hidden=true};
  function showOpts(on){$("optsCard").hidden=!on;$("opt").classList.toggle("on",on)}
  $("opt").onclick=function(){showOpts($("optsCard").hidden)};
  $("optX").onclick=function(){showOpts(false)};
  $("hostEdit").onclick=function(){$("hostIn").value=S.host||"";hostBox(true,"Modifier l'adresse de la U1");S.hostEditing=true;$("hostIn").focus()};
  $("uc").onchange=function(){post({command:"prefs_set",u1_code:$("uc").checked});say($("uc").checked?"Export : Preflight de la U1 exécuté dans Orca, avec vérifications.":"Export : fichier d'origine envoyé au Preflight de multiACE.","info")};
  $("gf").onchange=function(){post({command:"prefs_set",ace_guard:$("gf").checked});say($("gf").checked?"Garde-fou activé : séchage et poussée relancés si un ACE se déconnecte.":"Garde-fou désactivé.","info")};
  $("ah").onchange=function(){post({command:"prefs_set",auto_home:$("ah").checked});say($("ah").checked?"Homing automatique activé : la U1 fera son homing toute seule si besoin.":"Homing automatique désactivé : le panneau te demandera.","info")};
  window.orca&&window.orca.onMessage(function(m){
    if(!m)return;
    if(m.command==="host_result"){$("hostOk").disabled=false;if(m.ok){S.host=m.host;$("hostCur").textContent=m.host;hostBox(false);say("Adresse enregistrée : "+m.host,"ok")}else{hostBox(true,m.error||"Adresse invalide");}return}
    if(m.command==="state"){if(m.nohost){$("st").className="pill bad";$("st").textContent="sans adresse";hostBox(true);return}if(m.error){$("st").className="pill bad";$("st").textContent="hors ligne";say(m.error,"err");if(m.unreachable)hostBox(true,"La U1 ne répond pas à "+(S.host||"cette adresse")+" : vérifie l'adresse.");return}if(!S.hostEditing)hostBox(false);renderPrep(m.prep);if(S.edit){S.last=m.state||{};return}render(m.state||{})}
    else if(m.command==="prefs"){S.host=m.host||"";S.screen=m.screen||"off";S.cam=m.camera||"off";setCompact(!!m.compact);placeScreen();placeCam();S.prepPos=m.prep_pos==="bottom"?"bottom":"top";placePrep();S.fold=m.folds||{};applyFold();$("ah").checked=!!m.auto_home;$("gf").checked=m.ace_guard!==false;$("uc").checked=m.u1_code!==false;$("hostCur").textContent=S.host||"non renseignée";if(!S.host)hostBox(true)}
    else if(m.command==="done"){S.busy=false;say(m.text,m.ok?"info":"err");
      if(m.fix==="home"){var mm=$("msg");var b=document.createElement("div");b.style.marginTop="8px";
        b.innerHTML='<button class="fixbtn" data-r="1">Faire le homing puis reprendre</button> <button class="fixbtn ghost" data-r="0">Homing seul</button>';
        mm.appendChild(b);b.querySelectorAll("button").forEach(function(x){x.onclick=function(){S.busy=true;say("Homing en cours (G28)…","info");post({command:"home",retry:x.getAttribute("data-r")==="1"})}})}
      post({command:"refresh"})}
    else if(m.command==="status"){say(m.text,"info")}
    else if(m.command==="guard"){say(m.text,m.kind||"info");if(m.ask!=null){var gb=document.createElement("div");gb.style.marginTop="8px";gb.innerHTML='<button class="fixbtn">Relancer le séchage</button>';gb.querySelector("button").onclick=function(){post({command:"guard_dry",ace:m.ask});say("Séchage relancé…","info")};$("msg").appendChild(gb)}}
    else if(m.command==="queue"){renderQueue(m);if(S.last&&!S.edit)render(S.last)}
  });
  post({command:"prefs_get"});
  post({command:"refresh"});
  setInterval(function(){if(!document.hidden&&S.armed==null&&!(document.activeElement&&document.activeElement.tagName==="SELECT"))post({command:"refresh"})},4000);
})();
</script></body></html>"""


def action_label(name, a):
    """Libelle lisible d'une macro multiACE (numerotation 1-based comme sur la U1)."""
    def g(k):
        try:
            return int(a.get(k)) + 1
        except (TypeError, ValueError):
            return "?"
    if name == "ACE_SWAP_HEAD":
        return "Échange T%s ← ACE %s slot %s" % (g("HEAD"), g("ACE"), g("SLOT"))
    if name == "ACE_LOAD_HEAD":
        return "Chargement T%s ← ACE %s slot %s" % (g("HEAD"), g("ACE"), g("SLOT"))
    if name == "ACE_UNLOAD_HEAD":
        return "Déchargement T%s" % g("HEAD")
    if name == "ACE_UNLOAD_ALL_HEADS":
        return "Déchargement de toutes les têtes"
    if name == "ACE_DRY":
        try:
            d = int(a.get("DURATION"))
            dur = "%d h%s" % (d // 60, (" %02d" % (d % 60)) if d % 60 else "")
        except (TypeError, ValueError):
            dur = "?"
        return "Séchage ACE %s (%s °C, %s)" % (g("ACE"), a.get("TEMP"), dur)
    if name == "ACE_PA_CALIBRATE":
        return "Calibration du filament (PA) sur T%s" % g("HEAD")
    if name == "AUTO_BED_MESH_CALIBRATE":
        return "Calibration du plateau (%s °C)" % a.get("TEMP", 55)
    if name == "ACE_STOP_DRYING":
        return "Arrêt du séchage ACE %s" % g("ACE")
    return " ".join([name] + ["%s=%s" % kv for kv in a.items()])


QUEUE_POLL = 2.0
UNLOAD_SETTLE, UNLOAD_POLL = 12.0, 1.0
HEAD_MOVES = ("ACE_LOAD_HEAD", "ACE_SWAP_HEAD", "ACE_UNLOAD_HEAD", "ACE_UNLOAD_ALL_HEADS")
CALIBRATIONS = ("ACE_PA_CALIBRATE", "AUTO_BED_MESH_CALIBRATE")
NEEDS_HOME = HEAD_MOVES + CALIBRATIONS


class AcePanelController:
    """Panneau ancre a cote de la vue 3D (Preparer / Apercu). Une seule instance pour tout le plugin."""

    def __init__(self):
        self.panel = None
        self._lock = threading.Lock()
        self._refreshing = False
        self._action = False
        self._qlock = threading.Lock()
        self._queue, self._qid, self._qrun, self._paused = [], 0, False, False
        self.closed_by_user = False

    def open(self, force=False):
        """Ouvre (ou reaffiche) le panneau. Retourne un message."""
        if self.panel is not None and self.panel.is_open():
            self.panel.show()
            return "Panneau ACE affiche."
        if self.closed_by_user and not force:
            return "Panneau ferme par l'utilisateur."
        self.closed_by_user = False
        self.panel = orca.host.ui.create_dock_panel(
            html=PANEL.replace("__VERSION__", VERSION), title="multiACE", width=320, height=620,
            on_message=self.on_message, on_close=self.on_close, dock="right")
        return "Panneau ACE ouvert."

    def on_close(self):
        self.panel = None
        self.closed_by_user = True

    def hide(self):
        """Masque le panneau sans le fermer, et laisse une notification pour le rouvrir."""
        panel = self.panel
        if panel is None:
            return
        panel.hide()
        try:
            ui = orca.host.ui
            level = getattr(ui, "ImportantNotificationLevel", None) or getattr(ui.NotificationLevel, "ImportantNotificationLevel")
            ui.push_notification(level, "Panneau multiACE masqué.", "Afficher", self._show_from_notification)
        except Exception:
            pass

    def _show_from_notification(self):
        try:
            if self.panel is not None and self.panel.is_open():
                self.panel.show()
            else:
                self.open(force=True)
        except Exception:
            pass
        return True

    def _post(self, data):
        panel = self.panel
        if panel is not None:
            try:
                panel.post(data)
            except Exception:
                pass

    # Appele sur le fil de l'interface.
    def on_message(self, message):
        if isinstance(message, str):
            try:
                message = json.loads(message)
            except ValueError:
                return
        if not isinstance(message, dict):
            return
        cmd = message.get("command")
        if cmd == "refresh":
            self._refresh()
            return
        if cmd == "set_host":
            raw = str(message.get("host") or "")[:200]
            host = normalize_host(raw)
            if not host:
                self._post({"command": "host_result", "ok": False, "error": "Adresse invalide, par exemple 192.168.1.50"})
                return
            # Sur le fil de l'interface : OrcaSlicer peut demander l'autorisation pour cette adresse.
            try:
                MultiAce(host).get_json("/version", timeout=TIMEOUT_UI)
            except PermissionError:
                self._post({"command": "host_result", "ok": False, "error": permission_text(host)})
                return
            except Exception:
                self._post({"command": "host_result", "ok": False,
                            "error": "Pas de multiACE à %s : vérifie l'adresse (la U1 est-elle allumée ?)" % host})
                return
            st = load_settings()
            st["host"] = host
            save_settings(st)
            _probed.add(host)
            self._post({"command": "host_result", "ok": True, "host": host})
            self._refresh()
            return
        if cmd == "prefs_get":
            probe_network(effective_host())
            if remove_old_profile():
                self._post({"command": "done", "ok": True,
                            "text": "Ancien profil « Snapmaker U1 multiACE » supprimé (il disparaît de la liste au plus tard au prochain démarrage)."})
            st = load_settings()
            self._post({"command": "prefs", "host": effective_host(), "screen": st["screen"], "compact": st["compact"],
                        "prep_pos": st["prep_pos"], "folds": st["folds"], "camera": st["camera"],
                        "auto_home": st["auto_home"],
                        "ace_guard": st["ace_guard"], "u1_code": st["u1_code"], "real_nozzles": st["real_nozzles"]})
            _GUARD.ensure()
            return
        if cmd == "prefs_set":
            st = load_settings()
            if message.get("camera") in ("off", "top", "bottom"):
                st["camera"] = message["camera"]
            if message.get("screen") in ("off", "top", "bottom"):
                st["screen"] = message["screen"]
            if isinstance(message.get("compact"), bool):
                st["compact"] = message["compact"]
            if message.get("prep_pos") in ("top", "bottom"):
                st["prep_pos"] = message["prep_pos"]
            f = message.get("fold")
            if isinstance(f, dict) and isinstance(f.get("k"), str) and re.fullmatch(r"heads|prep|ace[0-7]", f["k"]) \
                    and isinstance(f.get("on"), bool):
                st["folds"] = dict(st.get("folds") or {}, **{f["k"]: f["on"]})
            if isinstance(message.get("auto_home"), bool):
                st["auto_home"] = message["auto_home"]
            if isinstance(message.get("ace_guard"), bool):
                st["ace_guard"] = message["ace_guard"]
            if isinstance(message.get("u1_code"), bool):
                st["u1_code"] = message["u1_code"]
            rn = message.get("real_nozzles")
            if isinstance(rn, list) and len(rn) == 4 and all(x in NOZZLE_CHOICES or x == "" for x in rn):
                st["real_nozzles"] = list(rn)
            try:
                save_settings(st)
            except OSError:
                pass
            return
        if cmd == "guard_dry":
            _GUARD.redo_dry(message.get("ace"))
            return
        if cmd == "hide":
            self.hide()
            return
        if cmd == "home":
            self._home(bool(message.get("retry")))
            return
        if cmd in ("queue_clear", "queue_remove", "queue_resume"):
            self._queue_cmd(cmd, message)
            return
        if cmd == "tap":
            try:
                x, y = int(message.get("x")), int(message.get("y"))
            except (TypeError, ValueError):
                return
            if 0 <= x < 4096 and 0 <= y < 4096:
                host = effective_host()

                def tap():
                    try:
                        MultiAce(host).screen_tap(x, y)
                    except PermissionError:
                        self._post({"command": "done", "ok": False, "text": permission_text(host)})
                    except Exception as e:
                        self._post({"command": "done", "ok": False, "text": "Toucher l'ecran : %s" % e})
                threading.Thread(target=tap, daemon=True).start()
            return
        script = None
        try:
            head = int(message.get("head"))
            if not 0 <= head <= 3:
                raise ValueError
        except (TypeError, ValueError):
            head = None
        if cmd in ("load", "swap") and head is not None:
            try:
                ace, slot = int(message.get("ace")), int(message.get("slot"))
            except (TypeError, ValueError):
                return
            if not (0 <= ace <= 7 and 0 <= slot <= 3):
                return
            script = ("ACE_SWAP_HEAD" if cmd == "swap" else "ACE_LOAD_HEAD", {"HEAD": head, "ACE": ace, "SLOT": slot})
        elif cmd == "unload" and head is not None:
            script = ("ACE_UNLOAD_HEAD", {"HEAD": head})
        elif cmd == "unload_all":
            script = ("ACE_UNLOAD_ALL_HEADS", {})
        elif cmd == "edit":
            self._edit(message)
            return
        elif cmd == "calib_pa" and head is not None:
            try:
                ace, slot = int(message.get("ace")), int(message.get("slot"))
            except (TypeError, ValueError):
                return
            if 0 <= ace <= 7 and 0 <= slot <= 3:
                # La bobine choisie d'abord sur sa tete (sautee si elle y est deja), puis la mesure,
                # forcee meme si une valeur existe : multiACE la memorise sur la bobine pour cette buse.
                self._run("ACE_LOAD_HEAD", {"HEAD": head, "ACE": ace, "SLOT": slot})
                self._run("ACE_PA_CALIBRATE", {"HEAD": head, "FORCE": 1})
            return
        elif cmd == "calib_bed":
            try:
                temp = int(message.get("temp") or 55)
            except (TypeError, ValueError):
                return
            if 40 <= temp <= 110:
                self._run("AUTO_BED_MESH_CALIBRATE", {"TEMP": temp})
            return
        elif cmd == "reset":
            try:
                ace, slot = int(message.get("ace")), int(message.get("slot"))
            except (TypeError, ValueError):
                return
            if 0 <= ace <= 7 and 0 <= slot <= 3:
                def job(client):
                    client.clear_override(ace, slot)
                    client.macro("MULTIACE_REFRESH_OVERRIDES", {}, timeout=60)
                self._work("Retour a l'identite RFID", job)
            return
        elif cmd in ("dry", "stopdry"):
            try:
                ace = int(message.get("ace"))
            except (TypeError, ValueError):
                return
            if not 0 <= ace <= 7:
                return
            if cmd == "stopdry":
                # Arreter le sechage est toujours sans risque, meme pendant une impression.
                _GUARD.expect_stop(ace)
                self._run("ACE_STOP_DRYING", {"ACE": ace}, allow_busy=True)
                return
            try:
                temp, duration = int(message.get("temp")), int(message.get("duration"))
            except (TypeError, ValueError):
                return
            if not (30 <= temp <= 55 and 10 <= duration <= 480):
                return
            # Comme l'interface web multiACE (ACE_DRY), aussi pendant une impression : multiACE 1.27b
            # garde l'assistance d'alimentation de la tete qui imprime pendant le changement d'ACE actif.
            self._run("ACE_DRY", {"ACE": ace, "TEMP": temp, "DURATION": duration}, allow_busy=True)
            return
        if script:
            self._run(*script)

    def _refresh(self):
        if _STOP.is_set():
            return
        host = effective_host()
        if not host:
            self._post({"command": "state", "nohost": True})
            return
        with self._lock:
            if self._refreshing:
                return
            self._refreshing = True

        def worker():
            try:
                client = MultiAce(host)
                state = client.state(timeout=TIMEOUT_UI)
                msg = {"command": "state", "state": state}
                setup = orca_filament_setup()
                if setup is not None and isinstance(state, dict):
                    real, src = effective_nozzles(client)
                    msg["prep"] = dict(slicing_advice(state, real, setup[0], setup[1]), real=real, real_src=src,
                                       manual=load_settings()["real_nozzles"])
                self._post(msg)
            except PermissionError:
                self._post({"command": "state", "error": permission_text(host)})
            except Exception as e:
                self._post({"command": "state", "error": str(e), "unreachable": "injoignable" in str(e)})
            finally:
                with self._lock:
                    self._refreshing = False

        threading.Thread(target=worker, daemon=True).start()

    def _edit(self, m):
        """Meme chemin que le selecteur de slot de multiACE : surcharge d'identite du slot
        (POST /slot-override) + ACE_SPOOL_SET sur la bobine associee (couleur, matiere, poids)."""
        try:
            ace, slot = int(m.get("ace")), int(m.get("slot"))
        except (TypeError, ValueError):
            return
        if not (0 <= ace <= 7 and 0 <= slot <= 3):
            return

        def clean(v, n=40):
            return gcode_safe(v, n)

        material = clean(m.get("material"), 16).upper() or "PLA"
        brand, subtype = clean(m.get("brand")), clean(m.get("subtype"))
        color = str(m.get("color") or "").strip()
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            self._post({"command": "done", "ok": False, "text": "Couleur invalide."})
            return
        weight = m.get("weight")
        try:
            weight = None if weight in (None, "") else int(round(float(weight)))
        except (TypeError, ValueError, OverflowError):
            weight = None
        if weight is not None and not 0 <= weight <= 65535:
            self._post({"command": "done", "ok": False, "text": "Poids invalide."})
            return
        apply_spool = bool(m.get("apply_spool", True))

        spool = m.get("spool")
        if spool is not None:
            spool = str(spool).strip()
            if spool not in ("", "new") and not spool.isdigit():
                self._post({"command": "done", "ok": False, "text": "Bobine invalide."})
                return

        def job(client):
            client.set_override(ace, slot, material, brand, subtype, color.lower())
            state = client.state(timeout=TIMEOUT_UI)
            sid = (state.get("spool_binding") or {}).get("%d_%d" % (ace, slot))
            sid = str(sid) if sid else None
            if spool == "new":
                # Nouvelle entree dans la table multiACE, liee directement a ce slot (comme le web).
                add = {"MATERIAL": material, "COLOR": color[1:].upper(), "ACE": ace, "SLOT": slot}
                if brand:
                    add["VENDOR"] = brand
                if subtype:
                    add["SUBTYPE"] = subtype
                if weight is not None:
                    add["WEIGHT"] = weight
                client.macro("ACE_SPOOL_ADD", add, timeout=60)
                client.macro("MULTIACE_REFRESH_OVERRIDES", {}, timeout=60)
                return
            if spool is not None and spool != (sid or ""):
                if spool:
                    client.macro("ACE_SPOOL_ASSIGN", {"ACE": ace, "SLOT": slot, "ID": spool}, timeout=60)
                    sid = spool
                else:
                    client.macro("ACE_SPOOL_ASSIGN", {"ACE": ace, "SLOT": slot}, timeout=60)   # detache
                    sid = None
            if sid:
                args = {"ID": sid}
                if apply_spool:
                    args.update(MATERIAL=material, COLOR=color[1:].upper(), SUBTYPE=subtype)
                    if brand:
                        args["VENDOR"] = brand
                if weight is not None:
                    args["WEIGHT"] = weight
                if len(args) > 1:
                    client.macro("ACE_SPOOL_SET", args, timeout=60)
            client.macro("MULTIACE_REFRESH_OVERRIDES", {}, timeout=60)

        self._work("Slot %d de l'ACE %d mis a jour" % (slot + 1, ace + 1), job)

    def _work(self, label, job):
        """Action de gestion (identite, poids) : autorisee meme pendant une impression, comme dans multiACE."""
        host = effective_host()
        with self._lock:
            if self._action:
                self._post({"command": "done", "ok": False, "text": "Une action est deja en cours."})
                return
            self._action = True

        def worker():
            try:
                job(MultiAce(host))
                self._post({"command": "done", "ok": True, "text": label + "."})
            except PermissionError:
                self._post({"command": "done", "ok": False, "text": permission_text(host)})
            except Exception as e:
                self._post({"command": "done", "ok": False, "text": "Echec : %s" % e})
            finally:
                with self._lock:
                    self._action = False

        threading.Thread(target=worker, daemon=True).start()

    # ------------------------------------------------------------ file d'attente des actions de tete
    # Charger / echanger / decharger s'enchainent dans l'ordre des clics. Chaque action est revue au
    # moment de partir (charger devient echanger si la tete est occupee, une action deja faite est
    # sautee). Au premier echec la file se met en pause : rien ne part tant que tu n'as pas repris.

    def _queue_post(self):
        with self._qlock:
            items = [{"id": it["id"], "label": it["label"], "status": it["status"], "name": it["name"],
                      "args": it["args"]} for it in self._queue]
            paused = self._paused
        self._post({"command": "queue", "items": items, "paused": paused})

    def _enqueue(self, name, args, allow_busy=False):
        with self._qlock:
            self._qid += 1
            self._queue.append({"id": self._qid, "name": name, "args": dict(args), "label": action_label(name, args),
                                "status": "attente", "allow_busy": allow_busy})
        self._queue_post()
        self._kick()

    def _kick(self):
        with self._qlock:
            if self._qrun or self._paused or not self._queue:
                return
            self._qrun = True
        threading.Thread(target=self._queue_worker, args=(effective_host(),), daemon=True).start()

    def _queue_worker(self, host):
        try:
            while True:
                with self._qlock:
                    if self._paused or not self._queue:
                        break
                    item = self._queue[0]
                    item["status"] = "en cours"
                self._queue_post()
                try:
                    ok, text, fix = self._exec(MultiAce(host), item["name"], item["args"],
                                               item.get("allow_busy", False), queued=True)
                except PermissionError:
                    ok, text, fix = False, permission_text(host), None
                except Exception as e:
                    ok, text, fix = False, "Echec de %s : %s" % (item["label"], friendly_error(str(e))), None
                with self._qlock:
                    if ok:
                        if self._queue and self._queue[0] is item:
                            self._queue.pop(0)
                    else:
                        item["status"] = "échec"
                        self._paused = True
                    rest = len(self._queue)
                msg = {"command": "done", "ok": ok, "text": text}
                if fix:
                    msg["fix"] = fix
                if not ok and rest > 1:
                    msg["text"] += " File en pause (%d action(s) en attente)." % (rest - 1)
                self._post(msg)
                self._queue_post()
        finally:
            with self._qlock:
                self._qrun = False
        self._kick()

    def _queue_cmd(self, cmd, message):
        with self._qlock:
            if cmd == "queue_clear":
                self._queue = [it for it in self._queue if it["status"] == "en cours"]
                self._paused = False
            elif cmd == "queue_remove":
                self._queue = [it for it in self._queue
                               if it["status"] == "en cours" or it["id"] != message.get("id")]
                if not any(it["status"] == "échec" for it in self._queue):
                    self._paused = False
            elif cmd == "queue_resume":
                for it in self._queue:
                    if it["status"] == "échec":
                        it["status"] = "attente"
                self._paused = False
        self._queue_post()
        self._kick()

    def _home(self, retry):
        host = effective_host()
        with self._qlock:
            if self._qrun:
                self._post({"command": "done", "ok": False, "text": "Une action est en cours : attends sa fin."})
                return
            self._qrun = True          # bloque la file pendant le homing

        def worker():
            ok = False
            try:
                client = MultiAce(host)
                state = client.state(timeout=TIMEOUT_UI)
                ps = str(state.get("printer_state") or "").lower()
                if ps in ("printing", "paused") or state.get("swap_in_progress"):
                    raise MultiAceError("la U1 imprime : pas de homing pendant une impression")
                self._post({"command": "status", "text": "Homing en cours (G28)…"})
                client.home()
                ok = True
                with self._qlock:
                    waiting = len(self._queue)
                self._post({"command": "done", "ok": True,
                            "text": "Homing terminé." + (" Reprise de la file (%d action(s))." % waiting
                                                         if retry and waiting else "")})
            except PermissionError:
                self._post({"command": "done", "ok": False, "text": permission_text(host)})
            except Exception as e:
                self._post({"command": "done", "ok": False, "text": "Homing : %s" % e})
            finally:
                with self._qlock:
                    self._qrun = False
            if ok and retry:
                self._queue_cmd("queue_resume", {})

        threading.Thread(target=worker, daemon=True).start()

    def _exec(self, client, name, args, allow_busy, queued=False):
        """Execute une macro multiACE. Retourne (ok, texte, correctif propose)."""
        state = client.state(timeout=TIMEOUT_UI)
        ps = str(state.get("printer_state") or "").lower()
        def occupied(st, p):
            return bool(st.get("swap_in_progress") or st.get("unload_all_active") or p == "busy")
        if queued and not allow_busy and ps not in ("printing", "paused") and occupied(state, ps):
            # U1 occupee (echange multiACE, macro ou homing en cours, lance d'ici ou d'ailleurs) :
            # on attend qu'elle se libere au lieu d'echouer.
            self._post({"command": "status", "text": "La U1 termine une opération : l'action suivante attend…"})
            end = time.time() + 600
            while occupied(state, ps) and ps not in ("printing", "paused") and time.time() < end:
                time.sleep(QUEUE_POLL)
                state = client.state(timeout=TIMEOUT_UI)
                ps = str(state.get("printer_state") or "").lower()
        if not allow_busy and (ps in ("printing", "paused") or state.get("swap_in_progress")
                               or (queued and ps == "busy")):
            why = {"printing": "en impression", "paused": "en pause", "busy": "occupée depuis plus de 10 min"}.get(
                ps, "échange multiACE en cours depuis plus de 10 min" if state.get("swap_in_progress") else ps)
            raise MultiAceError("la U1 est %s : action refusée. Regarde l'écran de la U1 et l'interface "
                                "multiACE, puis clique « Reprendre »." % why)
        heads = state.get("toolheads") or []
        if queued and name in HEAD_MOVES:
            # L'etat a pu changer depuis le clic (actions precedentes de la file) : on ajuste.
            try:
                h = int(args.get("HEAD", -1))
            except (TypeError, ValueError):
                h = -1
            th = heads[h] if 0 <= h < len(heads) else {}
            if name in ("ACE_LOAD_HEAD", "ACE_SWAP_HEAD"):
                if (th.get("filament_detected") and th.get("ace") == int(args["ACE"])
                        and th.get("slot") == int(args["SLOT"])):
                    return True, "Déjà en place : " + action_label(name, args), None
                name = "ACE_SWAP_HEAD" if th.get("filament_detected") else "ACE_LOAD_HEAD"
            elif name == "ACE_UNLOAD_HEAD" and th and not th.get("filament_detected"):
                return True, "Déjà vide : " + action_label(name, args), None
            elif name == "ACE_UNLOAD_ALL_HEADS" and heads and not any(x.get("filament_detected") for x in heads):
                return True, "Têtes déjà vides.", None
        label = action_label(name, args)
        auto_home = name in NEEDS_HOME and ps not in ("printing", "paused") and load_settings().get("auto_home")
        homed_now = False

        def do_home():
            self._post({"command": "status", "text": "Homing automatique (G28) avant : %s…" % label})
            client.home()

        if name in NEEDS_HOME:
            homed = client.homed_axes()
            if homed is not None and "z" not in homed.lower():
                if not auto_home:
                    # Klipper refuserait (« Must home Z axis first ») : on propose le homing d'abord.
                    return (False, "%s : la U1 n'est pas référencée (homing). Clique « Faire le homing puis "
                                   "reprendre » : la U1 fait son Home puis reprend." % label, "home")
                do_home()
                homed_now = True
        for attempt in (1, 2):
            try:
                client.macro(name, args, timeout=60 if name in ("ACE_DRY", "ACE_STOP_DRYING")
                             else 1800 if name in CALIBRATIONS else 900)
                break
            except PermissionError:
                raise
            except Exception as e:
                if "timed out" in str(e).lower():
                    return True, "Toujours en cours sur la U1 : " + label, None
                if needs_home(str(e)):
                    if auto_home and attempt == 1 and not homed_now:
                        do_home()           # verification impossible avant : homing puis un seul nouvel essai
                        homed_now = True
                        continue
                    return False, "%s impossible : %s" % (label, friendly_error(str(e))), "home"
                return False, "Echec de %s : %s" % (label, friendly_error(str(e))), None
        if name in ("ACE_UNLOAD_ALL_HEADS", "ACE_UNLOAD_HEAD"):
            # Le capteur de tete remonte avec un peu de retard (cache multiACE ~5 s) : on attend qu'il
            # passe a vide avant de conclure, au lieu de lire l'etat une seule fois.
            want = None if name == "ACE_UNLOAD_ALL_HEADS" else int(args.get("HEAD", -1))
            left, end = [], time.time() + UNLOAD_SETTLE
            while True:
                try:
                    now_heads = client.state(timeout=TIMEOUT_UI).get("toolheads") or []
                    left = [i for i, x in enumerate(now_heads)
                            if x.get("filament_detected") and (want is None or i == want)]
                except Exception:
                    left = []
                if not left or time.time() >= end:
                    break
                time.sleep(UNLOAD_POLL)
            if left:
                # multiACE a termine sans erreur : on ne bloque pas la file sur ce seul capteur, qui peut
                # rester a "detecte" alors que la tete est vide (constate sur la U1). Simple avertissement.
                names = ", ".join("T%d" % (i + 1) for i in left)
                return (True, "Terminé : %s. Le capteur de %s indique encore du filament : si la tête est "
                              "bien vide, ignore ce message ; sinon retire le reste à la main." % (label, names),
                        None)
        return True, "Terminé : " + label + (" (homing automatique fait avant)" if homed_now else ""), None

    def _run(self, name, args, allow_busy=False):
        if name in HEAD_MOVES or name in CALIBRATIONS or name == "ACE_DRY":
            # Le sechage passe aussi par la file, a sa place dans l'ordre des clics (file vide : il part
            # tout de suite). Il reste autorise pendant une impression, comme dans multiACE.
            self._enqueue(name, args, allow_busy)
            return
        host = effective_host()      # sechage : tout de suite, hors file (aussi pendant une impression)

        def worker():
            try:
                ok, text, fix = self._exec(MultiAce(host), name, args, allow_busy)
                msg = {"command": "done", "ok": ok, "text": text}
                if fix:
                    msg["fix"] = fix
                self._post(msg)
            except PermissionError:
                self._post({"command": "done", "ok": False, "text": permission_text(host)})
            except Exception as e:
                self._post({"command": "done", "ok": False,
                            "text": "Echec de %s : %s" % (action_label(name, args), friendly_error(str(e)))})

        threading.Thread(target=worker, daemon=True).start()


_PANEL = AcePanelController()


# --------------------------------------------------------------------------- garde-fou ACE
#
# Un ACE qui perd sa liaison USB redemarre : son sechage s'arrete et il ne pousse plus le filament.
# multiACE rearme deja la poussee de la tete qui imprime quand il reussit a se reconnecter ; le
# garde-fou est un filet en plus, cote OrcaSlicer :
#   - sechage : un ACE vu deconnecte puis revenu, dont le sechage s'est arrete, est relance avec la
#     meme temperature et le temps qu'il restait. Arret inexplique sans deconnexion vue (coupure plus
#     courte que le releve) : on demande, bouton « Relancer », on ne relance pas tout seul.
#     Un arret demande depuis le panneau ou un sechage automatique (multiACE) ne sont jamais touches ;
#   - poussee : pendant une impression, uniquement pour la tete qui imprime, si l'ACE qui l'alimente
#     ne pousse plus depuis GUARD_FA_LOST secondes (multiACE n'a pas repris la main). Jamais pour une
#     autre tete, jamais pendant un echange, au plus GUARD_FA_MAX essais.
# Fonctionne tant qu'OrcaSlicer est ouvert. Lecture de /api/state toutes les GUARD_POLL secondes.

GUARD_POLL = 2.0            # s entre deux releves
GUARD_SETTLE = 8.0          # s laisses a un ACE revenu (et a multiACE) avant d'agir
GUARD_DRY_MIN_LEFT = 180    # s : en dessous, le sechage etait de toute facon presque fini
GUARD_DRY_WINDOW = 30.0     # s : une deconnexion vue autant avant l'arret du sechage l'explique
GUARD_FA_LOST = 12.0        # s sans poussee sur la tete qui imprime avant d'intervenir
GUARD_FA_RETRY = 60.0       # s entre deux essais
GUARD_FA_MAX = 3            # essais par tete et par impression


def _drying_of(ace):
    """(temperature, secondes restantes) si l'ACE seche en ce moment, sinon None."""
    d = ace.get("dryer") if isinstance(ace.get("dryer"), dict) else {}
    if str(d.get("status") or "").lower() in ("", "stop", "free", "unknown"):
        return None
    try:
        temp, left = int(float(d.get("target_temp") or 0)), int(float(d.get("remain_time") or 0))
    except (TypeError, ValueError):
        return None
    return (temp, left) if 30 <= temp <= 70 and left > 0 else None


def _int_or_none(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


class AceGuard:
    """Decisions du garde-fou (sans reseau). step() recoit l'etat multiACE, la tete qui imprime et
    l'heure, et rend la liste des actions :
      ("dry", ace, temp, minutes)     relancer le sechage (deconnexion constatee)
      ("ask_dry", ace, temp, minutes) proposer de le relancer (arret inexplique)
      ("fa", ace, slot, head)         relancer la poussee de la tete qui imprime
      ("note", texte, genre)          information a afficher ("info" / "err")"""

    def __init__(self):
        self.aces = {}
        self.fa = {}
        self.stops = {}
        self.offer = {}

    def expect_stop(self, ace, now):
        self.stops[ace] = now + 60.0

    def step(self, state, head, now):
        out = []
        for a in state.get("aces") or []:
            i = _int_or_none(a.get("idx"))
            if i is None:
                continue
            r = self.aces.setdefault(i, {"conn": None, "dry": None, "lost": None, "back": None, "todo": None})
            conn = bool(a.get("connected"))
            if not conn:
                if r["conn"]:
                    r["lost"] = now
                    out.append(("note", "ACE %d déconnecté." % (i + 1), "err"))
                r["conn"] = False
                continue                       # on garde son dernier sechage en memoire
            if r["conn"] is False:
                r["back"] = now
                out.append(("note", "ACE %d revenu." % (i + 1), "info"))
            r["conn"] = True
            dry = _drying_of(a)
            if dry:
                r["dry"] = (dry[0], dry[1], now, bool(a.get("auto_dry_running")))
                r["todo"] = None
                continue
            if r["dry"]:
                temp, left, seen, auto = r["dry"]
                r["dry"] = None
                left -= now - seen
                if not auto and left >= GUARD_DRY_MIN_LEFT and self.stops.get(i, 0) < now:
                    sure = r["lost"] is not None and r["lost"] >= seen - GUARD_DRY_WINDOW
                    r["todo"] = {"temp": temp, "left": left, "at": now, "sure": sure}
            t = r["todo"]
            if t and now - max(t["at"], r["back"] or 0) >= GUARD_SETTLE:
                r["todo"] = None
                left = t["left"] - (now - t["at"])
                if left >= GUARD_DRY_MIN_LEFT:
                    minutes = max(10, min(480, int(-(-left // 60))))
                    out.append(("dry" if t["sure"] else "ask_dry", i, t["temp"], minutes))
        out += self._feed(state, head, now)
        return out

    def _feed(self, state, head, now):
        printing = str(state.get("printer_state") or "").lower() == "printing"
        if not printing or head is None:
            self.fa = {}
            return []
        if state.get("swap_in_progress"):
            return []
        th = next((t for t in state.get("toolheads") or [] if _int_or_none(t.get("idx")) == head), None)
        if not th or not th.get("head_source_known") or th.get("manual") or th.get("feeder"):
            return []
        ace, slot = _int_or_none(th.get("ace")), _int_or_none(th.get("slot"))
        unit = next((a for a in state.get("aces") or [] if _int_or_none(a.get("idx")) == ace), None)
        if ace is None or slot is None or not unit or not unit.get("connected") or not 0 <= slot <= 3:
            return []
        key = (head, ace, slot)
        if _int_or_none(unit.get("feed_assist")) != -1:
            f = self.fa.pop(key, None)
            if f and f["tries"]:
                return [("note", "Poussée revenue sur T%d (ACE %d slot %d)." % (head + 1, ace + 1, slot + 1), "info")]
            return []
        f = self.fa.setdefault(key, {"since": now, "tries": 0, "last": None, "told": False})
        if now - f["since"] < GUARD_FA_LOST or (f["last"] is not None and now - f["last"] < GUARD_FA_RETRY):
            return []
        if f["tries"] >= GUARD_FA_MAX:
            if not f["told"]:
                f["told"] = True
                return [("note", "T%d : la poussée de l'ACE %d ne reprend pas après %d essais. Vérifie l'ACE "
                         "(câble, hub) ; l'impression continue sans aide." % (head + 1, ace + 1, GUARD_FA_MAX), "err")]
            return []
        if _int_or_none(state.get("active_device")) != ace:
            # ACE_ENABLE_FEED_ASSIST agit sur l'ACE actif : sans lui on risquerait de pousser le mauvais.
            if not f["told"]:
                f["told"] = True
                return [("note", "T%d ne reçoit plus de poussée de l'ACE %d, mais ce n'est pas l'ACE actif : "
                         "rien envoyé par sécurité." % (head + 1, ace + 1), "err")]
            return []
        f["tries"] += 1
        f["last"] = now
        return [("fa", ace, slot, head)]


class GuardRunner:
    """Fil de fond du garde-fou : un seul pour tout le plugin."""

    def __init__(self):
        self._lock = threading.Lock()
        self._thread = None
        self.guard = AceGuard()
        self._asks = {}

    def ensure(self):
        if _STOP.is_set():
            return
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()

    def expect_stop(self, ace):
        with self._lock:
            self.guard.expect_stop(ace, time.monotonic())

    def _loop(self):
        host = None
        while not _STOP.wait(GUARD_POLL):
            try:
                st = load_settings()
                if not st.get("ace_guard", True) or not st.get("host"):
                    with self._lock:
                        self.guard = AceGuard()
                    continue
                if st["host"] != host:
                    host = st["host"]
                    with self._lock:
                        self.guard = AceGuard()
                client = MultiAce(host)
                try:
                    state = client.state(timeout=TIMEOUT_UI)
                except Exception:
                    continue                   # U1 injoignable : on ne conclut rien sur les ACE
                if not isinstance(state, dict):
                    continue
                head = None
                if str(state.get("printer_state") or "").lower() == "printing":
                    head = client.active_head()
                with self._lock:
                    actions = self.guard.step(state, head, time.monotonic())
                for act in actions:
                    self._do(client, act)
            except Exception:
                continue

    def _say(self, text, kind="info", ask=None, notify=False):
        msg = {"command": "guard", "text": text, "kind": kind}
        if ask is not None:
            msg["ask"] = ask
        _PANEL._post(msg)
        if notify:
            try:
                ui = orca.host.ui
                level = getattr(ui.NotificationLevel, "WarningNotificationLevel")
                if ask is not None:
                    ui.push_notification(level, text, "Relancer le séchage", lambda a=ask: self.redo_dry(a) or True)
                else:
                    ui.push_notification(level, text)
            except Exception:
                pass

    def _do(self, client, act):
        kind = act[0]
        if kind == "note":
            self._say(act[1], act[2], notify=act[2] == "err")
        elif kind == "dry":
            _, ace, temp, minutes = act
            try:
                client.macro("ACE_DRY", {"ACE": ace, "TEMP": temp, "DURATION": minutes}, timeout=60)
                self._say("ACE %d revenu : séchage relancé (%d °C, %d min restantes)." % (ace + 1, temp, minutes),
                          "info", notify=True)
            except Exception as e:
                self._say("ACE %d : relance du séchage impossible (%s)." % (ace + 1, friendly_error(str(e))),
                          "err", notify=True)
        elif kind == "ask_dry":
            _, ace, temp, minutes = act
            with self._lock:
                self._asks[ace] = (temp, minutes, time.monotonic())
            self._say("ACE %d : le séchage s'est arrêté avant la fin (il restait %d min à %d °C). "
                      "Coupure de l'ACE ?" % (ace + 1, minutes, temp), "err", ask=ace, notify=True)
        elif kind == "fa":
            _, ace, slot, head = act
            try:
                client.macro("ACE_ENABLE_FEED_ASSIST", {"INDEX": slot}, timeout=30)
                self._say("T%d : poussée relancée (ACE %d slot %d)." % (head + 1, ace + 1, slot + 1),
                          "info", notify=True)
            except Exception as e:
                self._say("T%d : relance de la poussée impossible (%s)." % (head + 1, friendly_error(str(e))),
                          "err", notify=True)

    def redo_dry(self, ace):
        """Bouton « Relancer le sechage » (panneau ou notification)."""
        ace = _int_or_none(ace)
        with self._lock:
            ask = self._asks.pop(ace, None)
        host = load_settings().get("host")
        if ask is None or not host:
            return
        temp, minutes, at = ask
        minutes = max(10, minutes - int((time.monotonic() - at) // 60))

        def worker():
            self._do(MultiAce(host), ("dry", ace, temp, minutes))

        threading.Thread(target=worker, daemon=True).start()


_GUARD = GuardRunner()


class AcePanel(orca.script.ScriptPluginCapabilityBase):
    """Plugins > "multiACE : panneau ACE" : rouvre le panneau s'il a ete ferme.

    Cette capacite est creee au chargement du plugin : c'est elle qui demarre tout (panneau, garde-fou),
    sans attendre que l'onglet multiACE soit ouvert."""

    def on_load(self):
        start_soon()

    def on_lifecycle_event(self, event, ctx):
        on_app_event(event, ctx)

    def on_unload(self):
        plugin_shutdown()

    def get_name(self):
        return "multiACE : panneau ACE"

    def execute(self):
        try:
            return orca.ExecutionResult.success(_PANEL.open(force=True))
        except Exception as e:
            return orca.ExecutionResult.skipped("Ouverture du panneau impossible : %s" % e)


PIPELINE_NAME = "multiACE : envoyer au Preflight"
_pipeline_lock = threading.Lock()


def _parse_strings(value):
    value = (value or "").strip()
    if not value:
        return []
    quoted = re.findall(r'"((?:[^"\\]|\\.)*)"', value)
    return quoted if quoted else [v.strip() for v in value.split(";") if v.strip()]


def ensure_pipeline_async(delay=2.0):
    """Ajoute "multiACE : envoyer au Preflight" au profil de traitement actif s'il est pour la U1 et ne l'a pas.

    La modification reste a enregistrer (etoile sur le profil), comme une modification faite a la main."""
    if not load_settings().get("auto_pipeline", True):
        return
    if not _pipeline_lock.acquire(blocking=False):
        return

    def worker():
        try:
            time.sleep(delay)
            bundle = orca.host.preset_bundle()
            model = bundle.current_printer_preset().config_value("printer_model") or ""
            if "U1" not in model:
                return
            current = _parse_strings(bundle.prints.edited_preset().config_value("slicing_pipeline_plugin"))
            if PIPELINE_NAME in current:
                return
            values = current + [PIPELINE_NAME]
            tx = orca.host.preset.process.begin_update()
            tx.set("slicing_pipeline_plugin", ";".join('"%s"' % v.replace('"', '') for v in values))
            tx.commit()
        except Exception:
            pass
        finally:
            _pipeline_lock.release()

    threading.Thread(target=worker, daemon=True).start()


def on_app_event(event, ctx):
    """Evenements d'OrcaSlicer (recus par l'onglet et par le panneau, sans doublon d'effet)."""
    names = ("PresetSelected", "ProjectOpened", "NewProject", "PlateSelected", "DeviceSelected")
    if any(event == getattr(orca.LifecycleEvent, n, object()) for n in names):
        auto_open_panel()
    if event == getattr(orca.LifecycleEvent, "PresetSelected", object()):
        kind = getattr(ctx, "msg", "") or ""
        if kind in ("print", "process", "printer"):
            ensure_pipeline_async()
    if event == getattr(orca.LifecycleEvent, "GCodeExportFinished", object()):
        try:
            _POPUP.show_pending()
        except Exception:
            pass


def start_soon():
    """Au chargement : l'adresse vient des reglages ou du profil imprimante (hote d'impression) ;
    on ouvre le panneau et on lance le garde-fou sans attendre l'onglet multiACE."""
    try:
        effective_host()
    except Exception:
        pass
    try:
        auto_open_panel()
    except Exception:
        pass


def auto_open_panel():
    """Ouverture automatique (une fois par session), sauf si l'utilisateur l'a desactivee ou fermee."""
    if _PANEL.panel is not None or _PANEL.closed_by_user:
        return
    if not load_settings().get("auto_panel", True):
        return
    try:
        _PANEL.open()
    except Exception:
        pass
    _GUARD.ensure()
    ensure_pipeline_async()


# --------------------------------------------------------------------------- script

class ResendLast(orca.script.ScriptPluginCapabilityBase):
    def on_unload(self):
        plugin_shutdown()

    def get_name(self):
        return "multiACE : renvoyer le dernier G-code"

    def execute(self):
        info = last_gcode_info()
        gcode_path, _ = last_gcode_paths()
        if not info or not os.path.exists(gcode_path):
            return orca.ExecutionResult.skipped("Aucun G-code garde pour l'instant.")
        host = load_settings()["host"]
        try:
            MultiAce(host).send_gcode(gcode_path, info.get("name"))
        except PermissionError:
            return orca.ExecutionResult.skipped(permission_text(host))
        except Exception as e:
            return orca.ExecutionResult.skipped("Envoi impossible : %s" % e)
        return orca.ExecutionResult.success("\"%s\" envoye au Preflight de %s." % (info.get("name"), host))


# --------------------------------------------------------------------------- enregistrement

@orca.plugin
class MultiAceBridge(orca.base):
    def register_capabilities(self):
        grants = {"threading": True}
        network = []
        host = ""
        try:
            host = load_settings()["host"]
        except Exception:
            host = ""
        if not host:
            # Pendant le chargement, le stockage du plugin n'est pas toujours disponible : on relit
            # les reglages a cote du dossier orca_plugins (<data_dir>/multiace_bridge/settings.json).
            try:
                parts = os.path.abspath(__file__).replace("\\", "/").split("/")
                if "orca_plugins" in parts:
                    base = "/".join(parts[: parts.index("orca_plugins")])
                    with open(os.path.join(base, "multiace_bridge", "settings.json"), encoding="utf-8") as f:
                        host = normalize_host(json.load(f).get("host") or "")
            except Exception:
                host = ""
        if host:
            network.append(origin_of(host))
        # network= : autorisation pour toute l'adresse (tous chemins et ports), demandee une fois.
        for kw in ("network", "network_http"):
            try:
                orca.request_permissions(**grants, **{kw: network})
                break
            except TypeError:
                continue
        else:
            orca.request_permissions(**grants)
        orca.register_capability(MultiAcePage)
        orca.register_capability(SendToPreflight)
        orca.register_capability(ResendLast)
        orca.register_capability(AcePanel)
