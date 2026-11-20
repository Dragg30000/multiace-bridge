# /// script
# requires-python = ">=3.12"
#
# [tool.orcaslicer.plugin]
# name = "multiACE Bridge (Snapmaker U1)"
# description = "Interface pour multiACE de decay71 (Snapmaker U1) dans OrcaSlicer : panneau ACE, interface web, attribution automatique des couleurs aux bobines a l'export et envoi a l'imprimante."
# author = "Dragg avec son ami Claude"
# version = "0.33.0"
# ///
"""multiACE Bridge - relie OrcaSlicer 2.5 a multiACE (decay71/multiACE) sur une Snapmaker U1.

Capacites :

* Onglet "multiACE" : l'interface web de multiACE (http://<U1>/multiace/) dans OrcaSlicer.
* Panneau ACE ancre : tetes, bobines, poids, sechage, ecran de la U1 ; charger / echanger /
  decharger / secher / calibrer dans une file d'attente ; homing automatique en option ;
  edition des slots et association des bobines de la table multiACE (slots sans RFID).
* Pipeline "multiACE : envoyer au Preflight" : a l'export (ou Imprimer), fenetre d'attribution
  des couleurs Orca aux bobines chargees, avec le moteur multiACE 1.27b livre avec le plugin
  (multiace_engine_127.py) ; plan optimal, purge par paire, alertes, choix au lancement
  (plateau, flux, camera) puis impression / envoi.
* Script "multiACE : renvoyer le dernier G-code".

Plugin communautaire, non officiel, sans lien avec Snapmaker ou OrcaSlicer. multiACE est le
projet de decay71 (github.com/decay71/multiACE) : ce plugin n'en est qu'une interface dans Orca.
Contient le moteur de multiACE (GPL-3.0) : le plugin est distribue sous GPL-3.0.
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

VERSION = "0.33.0"
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
    start = {"bed": True, "flow": False, "cam": False, "soft": True}
    ace_guard = data.get("ace_guard") if isinstance(data.get("ace_guard"), bool) else True
    real = data.get("real_nozzles") if isinstance(data.get("real_nozzles"), list) else []
    real_nozzles = [(real[h] if h < len(real) and real[h] in NOZZLE_CHOICES else "") for h in range(4)]
    if isinstance(data.get("start"), dict):
        start.update({k: v for k, v in data["start"].items() if k in start and isinstance(v, bool)})
    assign_mode = data.get("assign_mode") if data.get("assign_mode") in ("loaded", "layer", "optimize") else "loaded"
    profile_base = data.get("profile_base") if isinstance(data.get("profile_base"), str) else ""
    filaments = [x for x in data.get("filaments") or [] if isinstance(x, str)][:16]
    return {"host": host, "nozzle": nozzle, "auto_panel": auto_panel, "popup": popup,
            "screen": screen, "camera": camera, "compact": compact, "prep_pos": prep_pos, "folds": folds, "assign_mode": assign_mode,
            "profile_base": profile_base, "filaments": filaments, "auto_pipeline": auto_pipeline,
            "auto_home": auto_home, "start": start, "ace_guard": ace_guard,
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
            raise MultiAceError("Adresse de la U1 non renseignee : entre son IP dans l'onglet multiACE.")
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
        # Premier evenement d'interface apres le demarrage : on ouvre le panneau ACE.
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


# --------------------------------------------------------------------------- moteur d'attribution

# Moteur multiACE 1.27b de decay71 (multiace/tools/post_process_virtual_toolheads.py, GPL-3.0) :
# fichier multiace_engine_127.py livre avec le plugin, repris tel quel.
_engine_mod = None


def load_engine():
    """Moteur multiACE 1.27b livre avec le plugin (module multiace_engine_127)."""
    global _engine_mod
    if _engine_mod is None:
        try:
            from . import multiace_engine_127 as mod
        except ImportError:
            import multiace_engine_127 as mod
        _engine_mod = mod
    return _engine_mod


ENGINE_INFO = {"source": "embedded", "text": "moteur multiACE intégré (1.27b)"}


def prepare_engine(host=None):
    """Le plugin utilise toujours le moteur multiACE 1.27b livre avec lui."""
    return ENGINE_INFO

TIER_FR = {
    "exact_hex": "couleur identique", "name_exact": "même nom de couleur", "name_base": "couleur proche (nuance)",
    "name_canon": "couleur équivalente", "fuzzy": "couleur approchante",
    "loose_exact_hex": "matière différente", "loose_name_exact": "matière différente",
    "loose_name_base": "matière différente", "loose_name_canon": "matière différente",
    "loose_fuzzy": "matière et couleur approchantes", "fallback": "aucune couleur proche",
    "duplicate": "bobine partagée (mauvaise couleur)", "no_slot": "aucune bobine libre",
}
TIER_WARN = {"loose_exact_hex", "loose_name_exact", "loose_name_base", "loose_name_canon", "loose_fuzzy",
             "fallback", "duplicate", "no_slot"}


def live_slots_from_state(state):
    """Meme filtre que lookup_live_slots() du moteur : bobines connues (RFID ou saisie manuelle) seulement."""
    out = []
    for ace in state.get("aces") or []:
        idx = ace.get("idx")
        if not isinstance(idx, int) or idx > 3:
            continue
        for slot in ace.get("slots") or []:
            if slot.get("state") == "empty":
                continue
            if "source" in slot and slot["source"] not in ("rfid", "override"):
                continue
            color = (slot.get("color") or "").strip().lower()
            material = (slot.get("material") or "").strip()
            if color or material:
                out.append({"ace": idx, "slot": slot.get("idx"), "material": material, "color": color})
    return out


class AttributionError(Exception):
    def __init__(self, message, matches=None):
        super().__init__(message)
        self.matches = matches or []


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


def _last(pattern, *texts):
    found = None
    for text in texts:
        for m in re.finditer(pattern, text, re.M):
            found = m.group(1).strip()
    return found


def _split(value):
    return [v.strip() for v in re.split(r"[;,]", value or "") if v.strip()] if value else []


def gcode_meta(gcode):
    """Lecture legere : en-tete et fin du fichier seulement (ou OrcaSlicer ecrit ses reglages)."""
    head, tail = gcode[:2_000_000], gcode[-1_500_000:]
    colours = {i: _norm_colour(c) for i, c in enumerate(_split(_last(r"^;\s*filament_colou?r\s*=\s*(.+)$", head, tail)))}
    types = {i: t for i, t in enumerate(_split(_last(r"^;\s*filament_type\s*=\s*(.+)$", head, tail)))}
    grams = {}
    for i, g in enumerate(_split(_last(r"^;\s*filament used \[g\]\s*=\s*(.+)$", head, tail))):
        try:
            grams[i] = float(g)
        except ValueError:
            pass
    nozzle_raw = [v.strip().lower().replace(" ", "_") for v in
                  _split(_last(r"^;\s*nozzle_volume_type\s*=\s*(.+)$", head, tail))]
    nozzle = [NOZZLE_FR.get(v.replace("_", " "), v) for v in nozzle_raw]
    fmap = []
    for v in _split(_last(r"^;\s*filament_map\s*=\s*(.+)$", head, tail)):
        try:
            fmap.append(int(v) - 1)
        except ValueError:
            fmap.append(None)
    raw = _last(r"^;?\s*flush_volumes_matrix\s*=\s*([0-9.,\s]+)$", tail)
    mults = []
    for v in _split(_last(r"^;?\s*flush_multiplier\s*=\s*([0-9.,\s]+)$", tail)):
        try:
            mults.append(float(v))
        except ValueError:
            mults.append(1.0)
    mult = mults[0] if mults else 1.0
    mixed = {}
    flags = _split(_last(r"^;\s*filament_is_mixed\s*=\s*(.+)$", head, tail))
    comps = _quoted_list(_last(r"^;\s*filament_mixed_components\s*=\s*(.+)$", head, tail))
    ratios = _quoted_list(_last(r"^;\s*filament_mixed_sublayer_ratios\s*=\s*(.+)$", head, tail))
    for i, f in enumerate(flags):
        if f.strip() not in ("1", "true"):
            continue
        try:
            cs = [int(x) - 1 for x in (comps[i] if i < len(comps) else "").split(",") if x.strip()]
        except ValueError:
            cs = []
        try:
            rs = [float(x) for x in (ratios[i] if i < len(ratios) else "").split(",") if x.strip()]
        except ValueError:
            rs = []
        if len(cs) >= 2:
            mixed[i] = {"components": cs, "ratios": rs if len(rs) == len(cs) else []}
    thumb, best = None, 0
    for m in re.finditer(r"^; thumbnail(?:_(PNG|JPG))? begin (\d+)x(\d+) \d+\s*\n(.*?)^; thumbnail(?:_(?:PNG|JPG))? end",
                         head, re.M | re.S):
        area = int(m.group(2)) * int(m.group(3))
        if area > best and area <= 600 * 600:
            data = "".join(l.lstrip("; ").strip() for l in m.group(4).splitlines())
            thumb = "data:image/%s;base64,%s" % ("jpeg" if m.group(1) == "JPG" else "png", data)
            best = area
    return {"colours": colours, "types": types, "grams": grams, "nozzle": nozzle, "fmap": fmap,
            "matrix_raw": raw, "matrix_mult": max(1.0, mult) if mult and mult > 0 else 1.0,
            "matrix_mults": [max(1.0, m) if m > 0 else 1.0 for m in mults], "mixed": mixed, "thumb": thumb,
            "nozzle_raw": nozzle_raw}


def _quoted_list(value):
    """Liste de chaines OrcaSlicer : "a";"b,c";"" -> ["a", "b,c", ""] (sans guillemets : separees par ;)."""
    if not value:
        return []
    if '"' in value:
        return re.findall(r'"((?:[^"\\]|\\.)*)"', value)
    return [v.strip() for v in value.split(";")]


def flush_matrices(meta, eng):
    """Tables de purge par tete. OrcaSlicer 2.5 (machine multi-buses comme la U1) ecrit une table
    NxN par buse, a la suite (4 x 5 x 5 = 100 valeurs pour 5 filaments) : on les separe. Une table
    "plate" (valeur par defaut partout, ex. 280) n'a pas ete calculee d'apres les couleurs : on
    prend alors la premiere table calculee. Retourne une liste (une table par tete) ou None."""
    raw = meta.get("matrix_raw")
    if not raw:
        return None
    try:
        vals = [float(v) for v in raw.replace(" ", "").split(",") if v != ""]
    except ValueError:
        return None
    n = len(meta.get("colours") or {})
    if n >= 2 and len(vals) % (n * n) == 0 and len(vals) // (n * n) > 1:
        k = len(vals) // (n * n)
        blocks = []
        for b in range(k):
            blk = vals[b * n * n:(b + 1) * n * n]
            blocks.append([[blk[i * n + j] for j in range(n)] for i in range(n)])
    else:
        # OrcaSlicer ecrit la table deja multipliee par flush_multiplier (GCode::append_full_config) :
        # on ne la multiplie pas une deuxieme fois.
        if n >= 2 and len(vals) != n * n:
            return None         # taille inattendue : purge par defaut de multiACE plutot qu'une table mal lue
        one = eng._flush_matrix_build(raw, 1.0)
        return [one] * 4 if one else None

    def flat(mx):
        off = {mx[i][j] for i in range(n) for j in range(n) if i != j}
        return len(off) <= 1
    computed = next((b for b in blocks if not flat(b)), blocks[0])
    return [(blocks[h] if h < len(blocks) and not flat(blocks[h]) else computed) for h in range(4)]


def slot_weights(state):
    """Poids restant (g) par (ace, slot), d'apres la table des bobines de multiACE."""
    spools, binding, out = state.get("spools") or {}, state.get("spool_binding") or {}, {}
    for key, sid in binding.items():
        m = re.fullmatch(r"(\d+)_(\d+)", str(key))
        sp = spools.get(str(sid)) if m else None
        if sp and sp.get("weight_g") not in (None, ""):
            try:
                out[(int(m.group(1)), int(m.group(2)))] = float(sp["weight_g"])
            except (TypeError, ValueError):
                pass
    return out


def loadout_signature(state):
    """Empreinte des bobines presentes (pas des tetes) : change quand on charge, retire ou deplace une bobine."""
    return sorted("%s_%s_%s_%s" % (x["ace"], x["slot"], x["color"], (x["material"] or "").lower())
                  for x in all_slots_from_state(state))


def analyze_gcode(gcode, state, mode="loaded", forced=None, meta=None, real=None):
    """Attribution des couleurs du G-code aux bobines chargees, puis reecriture multiACE.

    mode : "loaded" (bobines telles qu'elles sont chargees) ou "optimize" (plan optimal : affiche les
    bobines a deplacer ; le lancement attend qu'elles le soient).
    forced : {filament (0-based): (ace, slot)} choisis a la main (n'importe quelle bobine presente).
    real : buses reelles des 4 tetes (reglage du plugin, "" = inconnue : on prend celle d'OrcaSlicer).
    Retourne un dict : gcode reecrit, correspondances, compteurs, alertes."""
    import contextlib
    import io
    eng = load_engine()
    meta = meta or gcode_meta(gcode)
    forced = {int(t): (int(v[0]), int(v[1])) for t, v in (forced or {}).items()}
    present = {(x["ace"], x["slot"]): x for x in all_slots_from_state(state)}
    for t, key in list(forced.items()):
        if key not in present:
            del forced[t]       # la bobine choisie n'est plus la
    weights = slot_weights(state)
    colours, types, grams = meta["colours"], meta["types"], meta["grams"]
    nozzle, fmap = meta["nozzle"], meta["fmap"]

    real = list(real or [])

    def sliced_type(h):
        """Buse de la tete h pour OrcaSlicer au moment du tranchage (en-tete du G-code)."""
        return nozzle[h] if h is not None and 0 <= h < len(nozzle) else None

    def head_type(h):
        """Buse reellement montee sur la tete h (reglage du plugin, sinon celle d'OrcaSlicer)."""
        if h is not None and 0 <= h < len(real) and real[h]:
            return real[h]
        return sliced_type(h)

    def sliced_head(t):
        if t < len(fmap) and fmap[t] is not None:
            return fmap[t]
        return t if t < 4 else None

    log = io.StringIO()
    with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
        if any(t.get("manual") for t in state.get("toolheads") or []):
            raise AttributionError("une tête est en mode manuel dans multiACE : l'attribution automatique "
                                   "ne peut pas la placer. Repasse-la en automatique.")
        body_at = _body_start(gcode)
        events = [int(x) for x in re.findall(r"^;\s*Change Tool\s*\d+\s*->\s*Tool\s*(\d+)", gcode[body_at:], re.M)]
        mixed = meta.get("mixed") or {}
        used = sorted(set(events)) or sorted(t for t in colours if t not in mixed)
        auto_ts = [t for t in used if t not in forced]
        live = live_slots_from_state(state)
        remap, info = {}, {}

        def table():
            return _matches(colours, types, used, forced, info, present, grams, weights, head_type, sliced_head,
                            sliced_type)

        if auto_ts:
            if not live:
                raise AttributionError("aucune bobine identifiée (RFID ou saisie manuelle) disponible pour les "
                                       "couleurs non choisies. Choisis une bobine pour chaque couleur ci-dessous.", table())
            missing = eng.check_material_availability({t: types.get(t) for t in auto_ts if t in types}, live)
            if missing:
                raise AttributionError("matière absente des ACE : %s. Choisis une bobine à la main ou charge-la."
                                       % ", ".join(m.upper() for m in missing), table())
            remap, info, _ = eng.match_colors_to_slots({t: colours[t] for t in auto_ts if t in colours}, live,
                                                       num_heads=4, filament_types=types,
                                                       strict_color=False, fuzzy_max_distance=None)
            remap = {t: v for t, v in remap.items() if t in auto_ts}
            for t in auto_ts:       # le moteur omet les filaments deja au bon numero
                sl = (info.get(t) or {}).get("slot")
                if t not in remap and sl:
                    remap[t] = sl["ace"] * 4 + sl["slot"]
            # Meme bobine en double (couleur + matiere) : prendre celle dont la tete a la buse prevue.
            taken = set(remap.values()) | {a * 4 + sl for a, sl in forced.values()}
            for t in auto_ts:
                sh = sliced_head(t)
                if t not in remap or sh is None or not sliced_type(sh):
                    continue
                cur = divmod(remap[t], 4)
                if head_type(cur[1]) == sliced_type(sh):
                    continue
                ref = present.get(cur) or {}
                alt = next((k for k, x in sorted(present.items())
                            if k != cur and k[0] * 4 + k[1] not in taken and x["color"] and x["color"] == ref.get("color")
                            and (x["material"] or "").lower() == (ref.get("material") or "").lower()
                            and head_type(k[1]) == sliced_type(sh)), None)
                if alt:
                    taken.discard(remap[t])
                    remap[t] = alt[0] * 4 + alt[1]
                    taken.add(remap[t])
                    info[t] = dict(info.get(t) or {}, slot=present[alt])
        for t, (ace, slot) in forced.items():
            remap[t] = ace * 4 + slot
        matches = table()
        lost = [m for m in matches if m["used"] and m["tier"] in ("no_slot", "duplicate", "fallback")]
        if lost:
            names = ", ".join("filament %d (%s %s)" % (m["t"] + 1, m["material"] or "?", m["color"] or "?") for m in lost)
            raise AttributionError("pas de bobine de la bonne couleur pour : %s. Choisis la bobine à utiliser "
                                   "dans la liste ci-dessous (ou corrige la couleur d'un slot dans le panneau)." % names,
                                   matches)
        num_aces = max(1, min(4, len(state.get("aces") or []) or 1))
        # Doublons exacts (meme couleur, meme matiere) de la bobine choisie, pour repartir les changements.
        copies = {}
        for t in used:
            if t not in remap:
                continue
            a0, s0 = divmod(remap[t], 4)
            ref = present.get((a0, s0)) or {}
            same = [k for k, x in sorted(present.items())
                    if k != (a0, s0) and x["color"] and x["color"] == ref.get("color")
                    and (x["material"] or "").lower() == (ref.get("material") or "").lower()
                    and (x.get("source") in ("rfid", "override") or t in forced)
                    and (head_type(k[1]) == head_type(s0))]          # meme type de buse uniquement
            copies[t] = [remap[t]] + [k[0] * 4 + k[1] for k in same]
        choice_loaded = _plan_heads(events, copies)
        swaps_loaded = _count_swaps(choice_loaded)
        plan = None
        current = {t: divmod(remap[t], 4) for t in used if t in remap}
        def head_ok(t, h):
            sh = sliced_head(t)
            return sh is None or head_type(h) is None or sliced_type(sh) is None or head_type(h) == sliced_type(sh)

        best = _best_placement(events, current, num_aces, head_ok)
        if best:
            placement, swaps_opt = best
            if swaps_opt < swaps_loaded:
                moves = [{"t": t, "color": colours.get(t, ""), "material": types.get(t, ""),
                          "from": list(current[t]) if t in current else None, "to": list(placement[t]),
                          "move": current.get(t) != placement[t],
                          "nozzle_warn": bool(head_type(placement[t][1]) and sliced_head(t) is not None
                                              and sliced_type(sliced_head(t)) != head_type(placement[t][1]))}
                         for t in used if t in placement]
                plan = {"swaps": swaps_opt, "moves": moves}
                plan.update(_plan_layout(moves, present, colours, types, num_aces))
        choice = choice_loaded
        gcode = _rewrite_per_event(gcode, body_at, events, choice)
        gcode, active, skipped, swapbacks = eng.rewrite(gcode)
        gcode, autoload = eng.inject_auto_load(gcode)
        owner = {}
        for t, lst in copies.items():
            for syn in lst:
                owner.setdefault(divmod(syn, 4), t)
        gcode, stamps = _stamp_purges(gcode, flush_matrices(meta, eng), owner, eng)
    dup = []
    for t, lst in copies.items():
        if len(lst) > 1:
            dup.append({"t": t, "color": colours.get(t, ""), "slots": [list(divmod(x, 4)) for x in lst]})
    alerts = []
    for m in matches:
        if m["used"] and m["low"]:
            alerts.append("Filament %d (%s) : il faut environ %d g, il reste %d g sur la bobine."
                          % (m["t"] + 1, m["color"], round(m["grams"]), round(m["remaining"])))
        if m["used"] and m["nozzle_warn"]:
            alerts.append("Filament %d : tranché pour une buse %s (T%d), imprimé sur T%d (%s)."
                          % (m["t"] + 1, m["sliced_type"], m["sliced_head"] + 1, m["slot"] + 1, m["head_type"]))
    mixed_info = []
    head_of = {t: remap[t] % 4 for t in used if t in remap}
    for mt, mx in sorted((meta.get("mixed") or {}).items()):
        parts = []
        for i, c in enumerate(mx["components"]):
            pct = (" %d %%" % round(mx["ratios"][i] * 100)) if mx["ratios"] else ""
            parts.append("filament %d%s" % (c + 1, pct))
        mixed_info.append({"t": mt, "color": colours.get(mt, ""), "components": mx["components"],
                           "text": "Mélange filament %d = %s (couches alternées par OrcaSlicer)" % (mt + 1, " + ".join(parts))})
        for c in mx["components"]:
            if c not in head_of:
                continue
            others = [u for u in used if u != c and head_of.get(u) == head_of[c] and u not in mx["components"]]
            if others:
                alerts.append("Mélange filament %d : le filament %d partage la tête T%d avec le filament %s : "
                              "un échange de bobine à chaque couche du mélange. Mets si possible chaque composant "
                              "seul sur sa tête." % (mt + 1, c + 1, head_of[c] + 1,
                                                                     ", ".join(str(u + 1) for u in others)))
    start_heads, pa_info = _start_and_pa(gcode, matches, state, meta)
    return {"gcode": gcode, "matches": matches, "used": used, "num_aces": num_aces, "mixed_info": mixed_info,
            "start_heads": start_heads, "pa_info": pa_info,
            "changes": len(events), "swaps_loaded": swaps_loaded, "swaps": swaps_loaded,
            "mode": "optimize" if (mode == "optimize" and plan) else "loaded", "plan": plan, "copies": dup,
            "active_swaps": active, "swapbacks": swapbacks, "autoload": autoload, "purge_stamps": stamps,
            "alerts": alerts, "nozzle_known": len(nozzle) >= 4,
            "nozzle_risk": [m["t"] for m in matches if m["used"] and m["nozzle_warn"]
                            and (m["grams"] is None or m["grams"] >= NOZZLE_BLOCK_G)], "signature": loadout_signature(state),
            "log": log.getvalue()}


def _start_and_pa(gcode, matches, state, meta):
    """Tetes chargees au depart (bloc auto-load de multiACE) et PA memorise par bobine.
    start_heads : [{head, ace, slot, t, color}] ; pa_info : [{t, color, ace, slot, head, start, pa, spool}]."""
    by_slot = {(m["ace"], m["slot"]): m for m in matches if m.get("used") and m.get("ace") is not None}
    start = []
    blk = re.search(r"^; multiACE auto-load: load.*?^; multiACE auto-load: end", gcode, re.M | re.S)
    if blk:
        for h, a, sl in re.findall(r"ACE_SWAP_HEAD HEAD=(\d+) ACE=(\d+) SLOT=(\d+)", blk.group(0)):
            h, a, sl = int(h), int(a), int(sl)
            m = by_slot.get((a, sl)) or {}
            start.append({"head": h, "ace": a, "slot": sl, "t": m.get("t"), "color": m.get("color", "")})
    start_slots = {(x["ace"], x["slot"]) for x in start}
    spools, binding = state.get("spools") or {}, state.get("spool_binding") or {}
    raw = meta.get("nozzle_raw") or []
    dia = str(load_settings().get("nozzle") or "0.4")
    try:
        dia = "%g" % float(dia)
    except ValueError:
        pass
    info = []
    for (a, sl), m in sorted(by_slot.items(), key=lambda kv: kv[1]["t"]):
        head = sl
        sid = binding.get("%d_%d" % (a, sl))
        sp = spools.get(str(sid)) if sid is not None else None
        vt = raw[head] if head < len(raw) and raw[head] else "standard"
        pam = (sp or {}).get("pa_matrix") or {}
        pa = pam.get("%s_%s" % (dia, vt))
        info.append({"t": m["t"], "color": m["color"], "ace": a, "slot": sl, "head": head,
                     "start": (a, sl) in start_slots, "spool": str(sid) if sid is not None else None,
                     "pa": float(pa) if isinstance(pa, (int, float)) else None})
    return start, info


FLOW_CAL_LINE_RE = re.compile(r"^\s*SM_PRINT_FLOW_CALIBRATE\b", re.I)
AUTO_LOAD_END_RE = re.compile(r"^\s*;\s*multiACE auto-load: end\b")
BARE_T_RE = re.compile(r"^\s*T(\d+)\s*(?:;.*)?$")
MESH_RE = re.compile(r"^\s*(?:BED_MESH_CALIBRATE|AUTO_BED_MESH_CALIBRATE)\b", re.I)
LAYER_RE = re.compile(r"^\s*;\s*LAYER_CHANGE\b")
M204_RE = re.compile(r"^\s*M204\s+S(\d+)", re.I)
TRAVEL_RE = re.compile(r"^(\s*G[01]\b)([^;]*?)\bF(\d+(?:\.\d*)?)([^;]*)(;.*)?$", re.I)
SOFT_START_F = 6000         # mm/min (100 mm/s) : vitesse max des deplacements avant la 1re couche
SOFT_START_ACCEL = 3000     # mm/s2 pendant ces deplacements
SOFT_START_LIFT = 5         # mm : on remonte d'abord la buse


def apply_print_prefs(in_path, out_path, bed_mesh=True, flow_cal=False, camera=False, heads=None, soft_start=True):
    """Meme traitement que le Preflight multiACE (preflight_core.prepend_print_prefs) : une ligne
    SET_PRINT_PREFERENCES ... FORCE=1 en tete (sinon une impression lancee hors ecran garde les reglages
    d'avant et imprime au PA 0,02 du slicer), celles du slicer neutralisees. Avec flow_cal, les
    SM_PRINT_FLOW_CALIBRATE du debut (avant le chargement auto : tetes vides) sont deplaces juste apres
    le bloc auto-load, une paire T<h> A0 + FLOW_CALIBRATE par tete ; heads limite les tetes mesurees
    (les autres gardent le PA deja connu / memorise sur la bobine).
    soft_start : entre la fin du chargement auto (ou du maillage du plateau) et la 1re couche, les
    deplacements sans extrusion plus rapides que SOFT_START_F sont ralentis, avec une acceleration
    reduite, et la buse remonte d'abord de SOFT_START_LIFT mm. Evite le choc de la tete qui sort de
    son support et traverse le plateau a 300 mm/s vers la ligne d'amorce (Y = 1)."""
    end_idx, initial, used = None, None, set()
    mesh_idx, layer_idx, accel = None, None, 10000
    with open(in_path, "r", encoding="utf-8", errors="replace") as src:
        for i, line in enumerate(src):
            m = BARE_T_RE.match(line)
            if m:
                h = int(m.group(1))
                if 0 <= h <= 3:
                    used.add(h)
                    if end_idx is None:
                        initial = h
                continue
            if layer_idx is None:
                if end_idx is None and AUTO_LOAD_END_RE.match(line):
                    end_idx = i
                elif MESH_RE.match(line):
                    mesh_idx = i
                elif LAYER_RE.match(line):
                    layer_idx = i
                else:
                    m2 = M204_RE.match(line)
                    if m2:
                        accel = int(m2.group(1))
    block, ins = [], None
    if flow_cal and end_idx is not None and used:
        todo = sorted(h for h in used if heads is None or h in heads)
        if initial is None:
            initial = min(used)
        ins = end_idx + 1
        block.append("; multiACE Bridge: calibration du flux (apres le chargement auto, tetes chargees)\n")
        order = [h for h in todo if h != initial] + ([initial] if initial in todo else [])
        for h in order:
            block.append("T%d A0\n" % h)
            block.append("FLOW_CALIBRATE EXTRUDER=%d\n" % h)
        block.append("T%d\n" % initial)
        block.append("; multiACE Bridge: calibration du flux fin\n")
    soft_from = (end_idx if end_idx is not None else mesh_idx) if soft_start else None
    if soft_from is not None and layer_idx is not None and soft_from > layer_idx:
        soft_from = None
    soft_on = False
    with open(out_path, "w", encoding="utf-8", newline="\n") as out:
        out.write("; multiACE Bridge: preferences d'impression\n")
        out.write("SET_PRINT_PREFERENCES BED_LEVEL=%d FLOW_CALIBRATE=%d TIME_LAPSE_CAMERA=%d FORCE=1\n"
                  % (1 if bed_mesh else 0, 1 if flow_cal else 0, 1 if camera else 0))
        with open(in_path, "r", encoding="utf-8", errors="replace") as src:
            i = -1
            for i, line in enumerate(src):
                if ins is not None and i == ins:
                    out.writelines(block)
                if line.lstrip().upper().startswith("SET_PRINT_PREFERENCES"):
                    out.write("; multiACE disabled: " + line.lstrip())
                    continue
                if not bed_mesh and line.lstrip().upper().startswith("SET_PRINT_AUTO_BED_LEVELING"):
                    # Le debut du G-code Snapmaker reactive le maillage : on respecte le choix « non ».
                    out.write("; multiACE Bridge disabled: " + line.lstrip())
                    continue
                if ins is not None and FLOW_CAL_LINE_RE.match(line):
                    out.write("; multiACE moved: " + line.lstrip())
                    continue
                if soft_from is not None and i > soft_from and (layer_idx is None or i < layer_idx):
                    t = TRAVEL_RE.match(line)
                    if t and " E" not in (" " + t.group(2) + t.group(4)).upper() and float(t.group(3)) > SOFT_START_F \
                            and re.search(r"\b[XY]-?\d", t.group(2) + t.group(4), re.I):
                        if not soft_on:
                            soft_on = True
                            out.write("; multiACE Bridge: deplacement doux vers la ligne d'amorce\n")
                            out.write("M204 S%d\nG91\nG1 Z%d F1200\nG90\n" % (SOFT_START_ACCEL, SOFT_START_LIFT))
                        out.write("%s%sF%d%s%s ; multiACE Bridge: F%s ralenti\n"
                                  % (t.group(1), t.group(2), SOFT_START_F, t.group(4).rstrip(), "", t.group(3)))
                        continue
                if soft_on and layer_idx is not None and i == layer_idx:
                    out.write("M204 S%d ; multiACE Bridge: acceleration d'origine\n" % accel)
                    soft_on = False
                out.write(line)
            if ins is not None and ins >= i + 1:
                out.writelines(block)
    return {"heads": [h for h in (block and sorted(used if heads is None else used & set(heads))) or []]}


def _plan_layout(moves, present, colours, types, num_aces):
    """Plan complet : etapes dans l'ordre (sans jamais poser une bobine sur une autre) et disposition
    finale de chaque ACE, slot 1 a 4. Une bobine non utilisee qui gene est retiree ; une boucle
    (A va chez B, B va chez A) est cassee en posant une bobine a cote le temps de l'echange."""
    occ = {}                                    # (ace, slot) -> ("t", n) | ("x", bobine)
    for k, x in present.items():
        occ[k] = ("x", x)
    for m in moves:
        if m["from"]:
            occ[tuple(m["from"])] = ("t", m["t"])
    pending = [dict(m, src=tuple(m["from"]) if m["from"] else None, dst=tuple(m["to"]))
               for m in moves if m["move"]]
    steps = []

    def spool(k):
        return present.get(k) or {}
    while pending:
        free = [m for m in pending if m["dst"] not in occ]
        if free:
            m = free[0]
            if m["src"] in occ and occ[m["src"]] == ("t", m["t"]):
                del occ[m["src"]]
            steps.append({"do": "move", "t": m["t"], "color": m["color"], "material": m["material"],
                          "from": list(m["src"]) if m["src"] else None, "to": list(m["dst"])})
            occ[m["dst"]] = ("t", m["t"])
            pending.remove(m)
            continue
        blocked = [m for m in pending if occ.get(m["dst"], ("t",))[0] == "x"]
        if blocked:
            k = blocked[0]["dst"]
            x = spool(k)
            steps.append({"do": "remove", "color": x.get("color", ""), "material": x.get("material", ""),
                          "from": list(k)})
            del occ[k]
            continue
        m = pending[0]                          # boucle : on pose cette bobine a cote
        if m["src"] in occ:
            del occ[m["src"]]
        steps.append({"do": "aside", "t": m["t"], "color": m["color"], "material": m["material"],
                      "from": list(m["src"]) if m["src"] else None})
        m["src"] = None
    layout = []
    for a in range(num_aces):
        for sl in range(4):
            cur, fin = present.get((a, sl)), occ.get((a, sl))
            if fin and fin[0] == "t":
                t = fin[1]
                moved = any(st.get("t") == t and st["do"] == "move" for st in steps)
                layout.append({"ace": a, "slot": sl, "t": t, "color": colours.get(t, ""),
                               "material": types.get(t, ""), "state": "moved" if moved else "keep"})
            elif fin:
                layout.append({"ace": a, "slot": sl, "t": None, "color": fin[1].get("color", ""),
                               "material": fin[1].get("material", ""), "state": "unused"})
            else:
                layout.append({"ace": a, "slot": sl, "t": None, "color": "", "material": "",
                               "state": "freed" if cur else "empty"})
    return {"steps": steps, "layout": layout}


def _stamp_purges(gcode, matrix, owner, eng):
    """Purge par paire de couleurs, comme le Preflight multiACE : ACE_SET_PURGE LENGTH=<mm> avant chaque
    echange (taille tiree de la table de purge d'OrcaSlicer, celle de la tete concernee),
    ACE_SET_PURGE RESET=1 au debut. matrix : liste d'une table par tete (ou une seule table)."""
    if matrix and not isinstance(matrix[0][0], list):
        matrix = [matrix] * 4
    if not matrix:
        return gcode, 0
    out, head_t, stamps, reset_done = [], {}, 0, False
    swap = re.compile(r"^ACE_SWAP_HEAD HEAD=(\d) ACE=(\d) SLOT=(\d)(.*)$")
    for line in gcode.split("\n"):
        m = swap.match(line)
        if m:
            h, a, sl, rest = int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4)
            to = owner.get((a, sl))
            if not reset_done:
                out.append("ACE_SET_PURGE RESET=1")
                reset_done = True
            if "INITIAL=1" not in rest:
                mm = eng._matrix_purge_mm(matrix[h] if h < len(matrix) else matrix[0], head_t.get(h), to)
                if mm is not None:
                    out.append("ACE_SET_PURGE LENGTH=%d" % mm)
                    stamps += 1
            head_t[h] = to
        out.append(line)
    return "\n".join(out), stamps


def _best_placement(events, current, num_aces, head_ok=None):
    """Repartition des couleurs sur les tetes (slot n -> tete n) qui minimise les echanges.

    Essaie chaque groupe de 4 couleurs "principales" (une par tete), range les autres sur les tetes
    les moins chargees (au plus num_aces bobines par tete), puis choisit l'ordre des tetes et les ACE
    qui demandent le moins de deplacements de bobines. Retourne ({filament: (ace, slot)}, echanges)."""
    from itertools import combinations, permutations
    colors = sorted(set(events))
    if not colors or len(colors) > 4 * num_aces:
        return None
    counts = {c: events.count(c) for c in colors}
    best_groups, best_swaps = None, None
    prims = list(combinations(colors, min(4, len(colors))))
    for primaries in prims:
        groups = [[c] for c in primaries] + [[] for _ in range(4 - len(primaries))]
        ok = True
        for c in sorted((c for c in colors if c not in primaries), key=lambda x: -counts[x]):
            h = min((h for h in range(4) if len(groups[h]) < num_aces), key=lambda h: len(groups[h]), default=None)
            if h is None:
                ok = False
                break
            groups[h].append(c)
        if not ok:
            continue
        head_of = {c: h for h, g in enumerate(groups) for c in g}
        loaded, swaps = {}, 0
        for c in events:
            h = head_of[c]
            if loaded.get(h) is not None and loaded[h] != c:
                swaps += 1
            loaded[h] = c
        if best_swaps is None or swaps < best_swaps:
            best_groups, best_swaps = groups, swaps
    if best_groups is None:
        return None
    best_place, best_moves = None, None
    for perm in permutations(range(4)):
        place, moves = {}, 0
        for gi, group in enumerate(best_groups):
            head = perm[gi]
            free = list(range(num_aces))
            keep = [c for c in group if current.get(c, (None, None))[1] == head and current[c][0] in free]
            for c in keep:
                place[c] = (current[c][0], head)
                free.remove(current[c][0])
            for c in group:
                if c not in place:
                    place[c] = (free.pop(0), head)
        moves = sum(1 for c, v in place.items() if current.get(c) != v)
        bad = sum(1 for c, v in place.items() if head_ok and not head_ok(c, v[1]))
        score = (bad, moves)        # d'abord respecter le type de buse, ensuite deplacer le moins possible
        if best_moves is None or score < best_moves:
            best_place, best_moves = place, score
    return best_place, best_swaps


def _count_swaps(choice):
    """Echanges de bobine : une tete qui avait deja une bobine en recoit une autre (chargements initiaux exclus)."""
    heads, swaps = {}, 0
    for syn in choice:
        h = syn % 4
        if heads.get(h) is not None and heads[h] != syn:
            swaps += 1
        heads[h] = syn
    return swaps


def _plan_heads(events, copies):
    """Pour chaque changement d'outil, choisit la copie physique (ACE*4+slot) a utiliser.

    Une couleur deja chargee sur une tete est reutilisee ; sinon on prend la copie dont la tete
    contient la bobine reutilisee le plus tard (strategie de Belady), pour limiter les echanges."""
    owners = {}
    for t, lst in copies.items():
        for syn in lst:
            owners.setdefault(syn, set()).add(t)
    heads, out = {}, []
    n = len(events)
    for i, t in enumerate(events):
        cands = copies.get(t) or [t]
        hit = [c for c in cands if heads.get(c % 4) == c]
        if hit:
            pick = hit[0]
        else:
            pick, best = cands[0], -1
            for c in cands:
                occ = heads.get(c % 4)
                if occ is None:
                    score = n + 1
                else:
                    who = owners.get(occ, set())
                    elsewhere = any(heads.get(o % 4) == o for w in who for o in copies.get(w, []) if o != occ)
                    if elsewhere:
                        score = n + 1
                    else:
                        score = next((j for j in range(i + 1, n) if events[j] in who), n + 1)
                if score > best:
                    pick, best = c, score
        heads[pick % 4] = pick
        out.append(pick)
    return out


def _rewrite_per_event(gcode, body_at, events, choice):
    """Remplace les numeros d'outil changement par changement (T, M104/M109 T, pre-extrusion)."""
    first = {}
    for t, syn in zip(events, choice):
        first.setdefault(t, syn)
    pre = gcode[:body_at]
    cur = dict(first)

    def sub_t(m):
        return "T%d" % cur.get(int(m.group(1)), int(m.group(1)))

    def fix(line):
        if re.match(r"^T\d{1,2}\s*$", line):
            return re.sub(r"T(\d{1,2})", sub_t, line, count=1)
        if re.match(r"^M10[49]", line):
            return re.sub(r"T(\d+)", sub_t, line)
        if line.startswith("SM_PRINT_PREEXTRUDE_FILAMENT"):
            return re.sub(r"INDEX=(\d+)", lambda m: "INDEX=%d" % cur.get(int(m.group(1)), int(m.group(1))), line)
        return line

    pre_out = "\n".join(fix(l) for l in pre.split("\n"))
    change = re.compile(r"^;\s*Change Tool\s*\d+\s*->\s*Tool\s*(\d+)")
    k, body_out = -1, []
    for line in gcode[body_at:].split("\n"):
        m = change.match(line)
        if m:
            k += 1
            if k < len(choice):
                cur[int(m.group(1))] = choice[k]
            body_out.append(line)
        else:
            body_out.append(fix(line))
    return pre_out + "\n".join(body_out)


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


def _matches(colours, types, used, forced, info, present, grams=None, weights=None, head_type=None, sliced_head=None,
             sliced_type=None):
    grams, weights = grams or {}, weights or {}
    head_type = head_type or (lambda h: None)
    sliced_head = sliced_head or (lambda t: None)
    sliced_type = sliced_type or head_type
    ts = sorted(set(colours) | set(used) | set(forced))
    out = []
    for t in ts:
        if t in forced:
            s = present.get(forced[t])
            tier = "forced"
        else:
            inf = info.get(t) or {}
            s, tier = inf.get("slot"), inf.get("tier") or ("no_slot" if t in used else None)
        bad = tier in ("no_slot", "duplicate", "fallback")
        slot_key = (s["ace"], s["slot"]) if s and not bad else None
        need = grams.get(t)
        left = weights.get(slot_key) if slot_key else None
        sh = sliced_head(t)
        ht = head_type(slot_key[1]) if slot_key else None
        st = sliced_type(sh) if sh is not None else None
        out.append({"t": t, "color": colours.get(t, ""), "material": types.get(t, ""), "used": t in used,
                    "tier": tier, "tier_fr": "choix manuel" if tier == "forced" else TIER_FR.get(tier, tier or "—"),
                    "warn": tier in TIER_WARN, "forced": tier == "forced",
                    "ace": s["ace"] if s else None, "slot": s["slot"] if s else None,
                    "slot_color": s["color"] if s else None, "slot_material": s["material"] if s else None,
                    "grams": need, "remaining": left,
                    "low": bool(need is not None and left is not None and left < need * 1.05 + 5),
                    "sliced_head": sh, "sliced_type": st, "head_type": ht,
                    "nozzle_warn": bool(st and ht and st != ht)})
    return out


def _body_start(gcode):
    m = re.search(r"^;\s*Change Tool\s*\d+\s*->\s*Tool\s*\d+", gcode, re.MULTILINE)
    return m.start() if m else len(gcode)


# --------------------------------------------------------------------------- fenetre d'attribution

ASSIGN_PAGE = r"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<style>
:root{--fg:#e9ecef;--muted:#9aa3ad;--line:rgba(255,255,255,.12);--accent:#009688;--bad:#e05a4f;--warn:#e0a030;
  color-scheme:dark;font:13px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}
*{box-sizing:border-box}body{margin:0;padding:16px 18px 24px;background:#1b1e22;color:var(--fg)}
.hdr{display:flex;gap:14px;align-items:center;margin-bottom:12px}
.hdr img{width:92px;height:92px;object-fit:contain;border-radius:10px;background:rgba(255,255,255,.04);border:1px solid var(--line)}
h1{font-size:16px;margin:0 0 2px}.sub{color:var(--muted);margin:0;font-size:12px}
.banner{border-radius:8px;padding:9px 12px;margin-bottom:10px;background:rgba(80,120,255,.14);color:#c9d3ff}
.alerts{border-radius:8px;padding:9px 12px;margin-bottom:10px;background:rgba(224,160,48,.13);color:#f1c27d}
.alerts div{margin:2px 0}
.stats{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:14px}
.stat{background:rgba(255,255,255,.04);border:1px solid var(--line);border-radius:9px;padding:8px 12px;min-width:120px}
.stat b{display:block;font-size:20px;font-variant-numeric:tabular-nums}.stat span{color:var(--muted);font-size:11.5px}
table{width:100%;border-collapse:collapse;margin-bottom:12px}
th{font-size:11px;text-transform:uppercase;letter-spacing:.6px;color:var(--muted);text-align:left;font-weight:600;padding:4px 6px;border-bottom:1px solid var(--line)}
td{padding:6px;border-bottom:1px solid var(--line);vertical-align:middle}
.sw{display:inline-block;width:16px;height:16px;border-radius:50%;border:1px solid rgba(255,255,255,.3);vertical-align:-3px;margin-right:6px;flex:none}
.arrow{color:var(--muted);text-align:center}
.tag{font-size:11px;border-radius:4px;padding:1px 6px;background:rgba(0,150,136,.18);color:#4fd1c0;white-space:nowrap}
.tag.warn{background:rgba(224,160,48,.18);color:var(--warn)}.tag.man{background:rgba(120,140,255,.18);color:#aab6ff}
.tag.noz{background:rgba(224,90,79,.18);color:#f08a80}.tag.nozok{background:rgba(0,150,136,.18);color:#4fd1c0}
.nozline{font-size:12px;opacity:.8;margin:0 0 6px}.card.stop{background:rgba(224,90,79,.13);color:#f6b0a8}.card.stop label{display:flex;gap:6px;align-items:center;margin-top:8px;color:#e8eaed;cursor:pointer}
.psub{margin:10px 0 4px;font-size:12px;color:#9aa4b2;text-transform:uppercase;letter-spacing:.04em}
ol.steps{margin:0 0 4px 18px;padding:0}ol.steps li{margin:4px 0}
table.lay{width:100%;border-collapse:collapse;margin:2px 0 8px;table-layout:fixed}
table.lay th,table.lay td{border:1px solid rgba(255,255,255,.08);padding:6px;font-size:12px;text-align:left;vertical-align:top}
table.lay th{color:#9aa4b2;font-weight:600}table.lay td.moved{background:rgba(66,133,244,.14)}
.tag.lay-mv{background:rgba(66,133,244,.22);color:#9cc0ff}.tag.lay-ok{background:rgba(0,150,136,.18);color:#4fd1c0}.tag.lay-un{background:rgba(255,255,255,.08);color:#9aa4b2}
.unused{opacity:.45}.muted{color:var(--muted)}
.err{background:rgba(224,90,79,.15);border-radius:8px;padding:12px;margin-bottom:12px}
.card{border-radius:8px;padding:12px;margin-bottom:12px}
.card.start{background:rgba(255,255,255,.04)}.opt{display:flex;align-items:center;gap:6px;margin:6px 0 0;cursor:pointer}
.optsub{margin:4px 0 4px 24px;font-size:12px}.card.start{user-select:none;-webkit-user-select:none}.mkw{width:62px;padding:1px 4px;margin-left:6px;background:#1c1f24;color:#e8eaed;border:1px solid rgba(255,255,255,.15);border-radius:4px}.optsub .opt{margin:3px 0}.later{margin:4px 0}.okc{color:#4fd1c0}.warnc{color:#f0b060}
button.mini{padding:2px 8px;font-size:11px;margin-left:6px}
.card.ok{background:rgba(0,150,136,.12)}.card.todo{background:rgba(224,160,48,.12)}
.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:12px 0}
button{background:var(--accent);color:#fff;border:0;border-radius:6px;padding:8px 14px;font:inherit;cursor:pointer}
button.ghost{background:transparent;color:var(--fg);border:1px solid var(--line)}
button.hot{background:#3d6bd8}
button:disabled{opacity:.4;cursor:default}
details{margin-top:8px;color:var(--muted)}pre{white-space:pre-wrap;font-size:11.5px;background:rgba(255,255,255,.04);padding:10px;border-radius:8px;max-height:260px;overflow:auto}
#msg{margin-top:8px;min-height:18px}#msg.err{padding:8px}#msg.ok{color:#3fb27f}
.hint{color:var(--muted);font-size:11.5px;margin:-4px 0 10px}
.pick{position:relative}
.pk{width:100%;display:flex;align-items:center;gap:6px;background:rgba(255,255,255,.06);color:var(--fg);border:1px solid var(--line);border-radius:6px;padding:5px 8px;font:inherit;cursor:pointer;text-align:left}
.pk .lbl{flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.pk.changed{border-color:#aab6ff}
.menu{position:absolute;z-index:10;left:0;right:0;top:calc(100% + 3px);background:#25292e;border:1px solid var(--line);border-radius:8px;padding:4px;box-shadow:0 8px 24px rgba(0,0,0,.5);max-height:300px;overflow:auto;min-width:330px}
.menu div{display:flex;align-items:center;gap:8px;padding:6px 8px;border-radius:5px;cursor:pointer}
.menu div:hover,.menu div.sel{background:rgba(255,255,255,.08)}
small{color:var(--muted)}
.loading{display:flex;align-items:center;gap:12px;padding:30px 0;color:var(--muted)}
.spin{width:22px;height:22px;border:3px solid rgba(255,255,255,.15);border-top-color:#009688;border-radius:50%;animation:r 1s linear infinite}
@keyframes r{to{transform:rotate(360deg)}}
</style></head><body>
<div class="hdr"><img id="thumb" hidden alt=""><div><h1 id="title"></h1><p class="sub" id="sub"></p></div></div>
<div id="body"></div>
<script>
var D=__DATA__;
(function(){
  var $=function(i){return document.getElementById(i)};
  function esc(x){var d=document.createElement("span");d.textContent=x==null?"":String(x);return d.innerHTML}
  function col(c){var m=/^#?([0-9a-fA-F]{6})([0-9a-fA-F]{2})?$/.exec(String(c||"").trim());return m?"#"+m[1]:"#777"}
  function post(m){window.orca&&window.orca.postMessage(m)}
  function rgb(h){h=col(h).slice(1);return [parseInt(h.slice(0,2),16),parseInt(h.slice(2,4),16),parseInt(h.slice(4,6),16)]}
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
  function swatch(h){return '<span class="sw" style="background:'+col(h)+'"></span>'}
  function where(a){return a?"ACE "+(a[0]+1)+" · slot "+(a[1]+1)+" (T"+(a[1]+1)+")":"—"}
  var S={armed:null,forced:{},nozok:false};

  function render(D){
    window.D=D;S.forced=D.forced||{};S.armed=null;S.nozok=false;
    $("title").textContent=D.name||"Attribution multiACE";
    if(D.thumb){$("thumb").src=D.thumb;$("thumb").hidden=false}
    var R=D.result||{},matches=R.matches||D.matches||[],slots=D.slots||[];
    var top=(D.banner?'<div class="banner">'+esc(D.banner)+'</div>':"");
    if(D.loading){$("sub").textContent="";$("body").innerHTML=top+'<div class="loading"><div class="spin"></div>'+esc(D.loading)+'</div>';return}
    function optHtml(v,m){
      if(v==="auto"){var ok=!m.forced&&m.ace!=null&&!m.warn;
        return (ok?swatch(m.slot_color):'<span class="sw" style="background:transparent;border-style:dashed"></span>')+
          '<span class="lbl">Automatique'+(ok?' · '+esc(cname(m.slot_color))+' <small>ACE '+(m.ace+1)+' · slot '+(m.slot+1)+'</small>':(m.forced?'':' <small>(aucune)</small>'))+'</span>'}
      var s=slots.filter(function(x){return x.ace+"_"+x.slot===v})[0];if(!s)return esc(v);
      var noz=s.head_type?' · '+esc(s.head_type):'';
      var bad=nozBad(m,s),good=m.sliced_type&&s.head_type&&!bad;
      return swatch(s.color)+'<span class="lbl">'+esc(cname(s.color))+' <small>'+esc((s.brand?s.brand+" ":"")+(s.material||""))+
        ' · ACE '+(s.ace+1)+' slot '+(s.slot+1)+' → T'+(s.slot+1)+noz+(s.weight!=null?' · ≈ '+Math.round(s.weight)+' g':'')+(s.source==="derived"?" · déduite":"")+'</small>'+
        (bad?' <span class="tag noz">buse ≠ '+esc(m.sliced_type)+'</span>':(good?' <span class="tag nozok">bonne buse</span>':''))+'</span>';
    }
    function nozBad(m,s){return !!(m.sliced_type&&s.head_type&&m.sliced_type!==s.head_type)}
    function chooser(m){
      if(!slots.length)return "";
      var cur=S.forced[String(m.t)]||"auto",want=cname(m.color);
      // La bonne couleur d'abord (bonne buse avant mauvaise buse), puis les autres couleurs.
      var rank=function(s){return (cname(s.color)===want?0:2)+(nozBad(m,s)?1:0)};
      var vals=["auto"].concat(slots.map(function(s,i){return {s:s,i:i}}).sort(function(a,b){return rank(a.s)-rank(b.s)||a.i-b.i})
        .map(function(x){return x.s.ace+"_"+x.s.slot}));
      return '<div class="pick" data-t="'+m.t+'" data-v="'+cur+'"><button type="button" class="pk">'+optHtml(cur,m)+'<span>▾</span></button>'+
        '<div class="menu" hidden>'+vals.map(function(v){return '<div data-v="'+v+'"'+(v===cur?' class="sel"':'')+'>'+optHtml(v,m)+'</div>'}).join("")+'</div></div>';
    }
    function table(){
      var noz=matches.some(function(m){return m.sliced_type});
      var ht={};slots.forEach(function(s){if(s.head_type)ht[s.slot]=s.head_type});
      var heads=[0,1,2,3].filter(function(h){return ht[h]}).map(function(h){return 'T'+(h+1)+' '+esc(ht[h])}).join(' · ');
      return (heads?'<div class="nozline">Buses de la U1 : '+heads+' — le slot d’une bobine décide de sa tête (slot 3 → T3).</div>':'')+'<table><tr><th>Slicer</th><th></th><th>Bobine</th><th>Correspondance</th><th>Forcer une bobine</th></tr>'+matches.map(function(m){
        var target=m.ace==null||m.tier==="no_slot"||m.tier==="duplicate"||m.tier==="fallback"?'<span class="tag warn">à choisir</span>':
          swatch(m.slot_color)+esc(cname(m.slot_color))+' <span class="muted">ACE '+(m.ace+1)+' · slot '+(m.slot+1)+' → T'+(m.slot+1)+'</span>'+
          (m.remaining!=null?' <small>≈ '+Math.round(m.remaining)+' g</small>':'');
        var tags='<span class="tag'+(m.forced?" man":(m.warn?" warn":""))+'">'+esc(m.tier_fr)+'</span>'+
          (m.nozzle_warn?' <span class="tag noz">buse '+esc(m.head_type)+' ≠ '+esc(m.sliced_type)+'</span>':'')+
          (m.low?' <span class="tag warn">filament juste</span>':'');
        var left=swatch(m.color)+'Filament '+(m.t+1)+' · '+esc(cname(m.color))+' <span class="muted">'+esc(m.material)+'</span>'+
          (m.grams!=null?' <small>'+Math.round(m.grams)+' g</small>':'')+(m.sliced_type?'<br><small>tranché pour T'+(m.sliced_head+1)+' · '+esc(m.sliced_type)+'</small>':'')+(m.used?"":" (non utilisé)");
        return '<tr class="'+(m.used?"":"unused")+'"><td>'+left+'</td><td class="arrow">→</td><td>'+target+'</td><td>'+tags+'</td><td style="width:34%">'+(m.used?chooser(m):"")+'</td></tr>';
      }).join("")+'</table><p class="hint">Choisis une bobine dans la dernière colonne pour imposer ta couleur, puis « Recalculer ».'+(noz?' Le type de buse de chaque tête est rappelé.':'')+'</p>';
    }
    var recalc='<button class="hot" data-a="recalc" disabled>Recalculer avec mes choix</button>';
    $("sub").textContent=D.error?"Attribution impossible pour l’instant":
      ((R.used||[]).length+" couleur(s) associée(s) aux bobines des ACE · "+(D.busy?"la U1 imprime : lancement impossible pour l'instant":"U1 prête"));
    if(D.error){
      $("body").innerHTML=top+'<div class="err">'+esc(D.error)+'</div>'+(matches.length?table():"")+
        '<div class="row">'+(matches.length?recalc:"")+(D.perm?'<button class="hot" data-a="retry">Autoriser et réessayer</button>':"")+
        '<button class="ghost" data-a="preflight">Ouvrir dans le Preflight multiACE</button><button class="ghost" data-a="close">Fermer</button></div><div id="msg"></div>'+
        (D.log?'<details><summary>Détails</summary><pre>'+esc(D.log)+'</pre></details>':"");
      return;
    }
    var alerts=(R.alerts||[]).length?'<div class="alerts">'+R.alerts.map(function(a){return '<div>⚠ '+esc(a)+'</div>'}).join("")+'</div>':"";
    var stats='<div class="stats"><div class="stat"><b>'+R.changes+'</b><span>changements d\'outil</span></div>'+
      '<div class="stat"><b>'+R.swaps+'</b><span>échanges de bobine (ACE)</span></div>'+
      '<div class="stat"><b>'+R.autoload+'</b><span>tête(s) chargée(s) automatiquement au départ</span></div>'+
      (R.purge_stamps?'<div class="stat"><b>'+R.purge_stamps+'</b><span>purges ajustées par couleur</span></div>':'')+'</div>';
    function moveList(p){
      var warn={};p.moves.forEach(function(m){if(m.nozzle_warn)warn[m.t]=1});
      var st=(p.steps||[]).map(function(s,i){var c=swatch(s.color)+'<b>'+esc(cname(s.color))+'</b>'+(s.t!=null?' <span class="muted">filament '+(s.t+1)+'</span>':'');
        var txt=s.do==="move"?c+' : '+(s.from?where(s.from):'(posée à côté)')+' → <b>'+where(s.to)+'</b>'+(warn[s.t]?' <span class="tag noz">autre buse</span>':'')
          :s.do==="remove"?'Retire '+c+' de '+where(s.from)+' <span class="muted">(pas utilisée pour cette impression)</span>'
          :'Sors '+c+' de '+where(s.from)+' et pose-la à côté un instant';
        return '<li>'+txt+'</li>'}).join("");
      var lab={moved:'<span class="tag lay-mv">à mettre</span>',keep:'<span class="tag lay-ok">en place</span>',unused:'<span class="tag lay-un">pas utilisée</span>',freed:'<span class="tag lay-un">libérée</span>',empty:''};
      var rows={};(p.layout||[]).forEach(function(c){(rows[c.ace]=rows[c.ace]||[])[c.slot]=c});
      var grid='<table class="lay"><tr><th></th><th>Slot 1 (T1)</th><th>Slot 2 (T2)</th><th>Slot 3 (T3)</th><th>Slot 4 (T4)</th></tr>'+
        Object.keys(rows).sort().map(function(a){return '<tr><th>ACE '+(+a+1)+'</th>'+rows[a].map(function(c){
          return '<td class="'+c.state+'">'+(c.color?swatch(c.color)+esc(cname(c.color))+(c.t!=null?' <span class="muted">fil. '+(c.t+1)+'</span>':''):'<span class="muted">vide</span>')+'<br>'+lab[c.state]+'</td>'}).join("")+'</tr>'}).join("")+'</table>';
      return (st?'<div class="psub">Dans l’ordre :</div><ol class="steps">'+st+'</ol>':'')+'<div class="psub">Disposition finale :</div>'+grid}
    var planCard="",optimizing=R.mode==="optimize"&&R.plan;
    if(optimizing){
      planCard='<div class="card todo"><b>Déplace ces bobines</b> ('+R.plan.swaps+' échanges au lieu de '+R.swaps+') — la fenêtre se met à jour toute seule dès que c’est fait :'+moveList(R.plan)+
        '<div class="row" style="margin-bottom:0"><button class="ghost" data-a="plan-off">Garder les bobines telles qu’elles sont</button></div></div>';
    } else if(R.plan){
      planCard='<div class="card ok"><b>Plan optimal :</b> '+R.plan.swaps+' échanges au lieu de '+R.swaps+' en déplaçant '+R.plan.moves.filter(function(m){return m.move}).length+' bobine(s).'+moveList(R.plan)+
        '<div class="row" style="margin-bottom:0"><button class="hot" data-a="plan-on">Utiliser ce plan</button></div></div>';
    }
    var dup=(R.copies||[]).length?'<div class="hint" style="margin:0 0 10px">Couleurs en double utilisées : '+R.copies.map(function(c){
      return swatch(c.color)+esc(cname(c.color))+' ('+c.slots.map(function(x){return "ACE "+(x[0]+1)+" slot "+(x[1]+1)}).join(" + ")+')'}).join(", ")+'</div>':"";
    if((R.mixed_info||[]).length)dup+='<div class="hint" style="margin:0 0 10px">'+R.mixed_info.map(function(m){return swatch(m.color)+esc(m.text)}).join("<br>")+'</div>';
    var startCard="";
    if(!optimizing&&R.matches){
      if(!S.opt){var pr=D.prefs||{};S.opt={bed:pr.bed!==false,flow:!!pr.flow,cam:!!pr.cam,soft:pr.soft!==false,heads:{}}}
      var sh=R.start_heads||[],pi=R.pa_info||[];
      sh.forEach(function(x){if(S.opt.heads[x.head]===undefined)S.opt.heads[x.head]=true});
      var ck=function(k,txt,tip){return '<label class="opt" title="'+esc(tip)+'"><input type="checkbox" data-o="'+k+'"'+(S.opt[k]?" checked":"")+'> '+txt+'</label>'};
      var flowList="";
      if(S.opt.flow){
        flowList='<div class="optsub">'+(sh.length?'<div class="muted">Mesurées au départ (têtes chargées) :</div>'+sh.map(function(x){
            return '<label class="opt"><input type="checkbox" data-h="'+x.head+'"'+(S.opt.heads[x.head]?" checked":"")+'> T'+(x.head+1)+' · '+swatch(x.color)+esc(cname(x.color))+(x.t!=null?' <span class="muted">filament '+(x.t+1)+'</span>':'')+'</label>'}).join(""):'<div class="muted">Aucune tête chargée au départ.</div>')+
          pi.filter(function(p){return !p.start}).map(function(p){
            return '<div class="later">'+swatch(p.color)+esc(cname(p.color))+' <span class="muted">filament '+(p.t+1)+' · arrive en cours d’impression (T'+(p.head+1)+')</span> — '+
              (p.pa!=null?'<span class="okc">PA mémorisé '+p.pa.toFixed(4)+'</span>':'<span class="warnc">pas de PA mémorisé'+(p.spool?'':' (aucune bobine associée au slot)')+'</span>')+
              (p.spool?' <button class="ghost mini" data-a="precal" data-head="'+p.head+'" data-ace="'+p.ace+'" data-slot="'+p.slot+'">Calibrer avant</button>':
                ' <span class="mk"><input type="number" class="mkw" min="0" max="5000" step="10" value="1000" title="Poids restant (g)"> g <button class="ghost mini" data-a="mkspool" data-ace="'+p.ace+'" data-slot="'+p.slot+'" title="Crée la bobine dans la table multiACE avec la couleur et la matière du slot, puis permet de la calibrer">Créer la bobine</button></span>')+'</div>'}).join("")+'</div>';
      }
      startCard='<div class="card start"><b>Au lancement</b>'+
        ck("bed","Calibration du plateau (maillage sur la zone imprimée)","Le début du G-code mesure le plateau à la température d’impression. Décoché : la U1 garde le maillage précédent.")+
        ck("flow","Calibration du flux (PA) au départ","Mesure le PA des têtes cochées juste après leur chargement automatique, comme le Preflight multiACE. Décoché : PA du slicer.")+flowList+
        ck("cam","Time-lapse caméra","")+
        ck("soft","Déplacement doux vers la ligne d’amorce","Après le chargement des têtes, la tête traverse le plateau à 300 mm/s vers le bord avant pour la ligne d’amorce (choc). Coché : 100 mm/s, accélération réduite et buse remontée de 5 mm avant.")+
        (R.autoload?'<div class="hint" style="margin-top:6px">Chargement automatique : les têtes vides ou avec une autre bobine au départ sont chargées depuis les ACE avant la première couche ('+R.autoload+' tête(s)).</div>':"")+'</div>';
    }
    var risk=(R.nozzle_risk||[]).map(function(t){return matches.filter(function(m){return m.t===t})[0]}).filter(Boolean);
    var stopCard=risk.length&&!optimizing?'<div class="card stop"><b>⛔ Mauvais type de buse</b>'+risk.map(function(m){
        var under=m.sliced_type==="Haut débit"&&m.head_type!=="Haut débit";
        return '<div>Filament '+(m.t+1)+' · '+swatch(m.color)+esc(cname(m.color))+(m.grams!=null?' ('+Math.round(m.grams)+' g)':'')+
          ' : tranché pour une buse '+esc(m.sliced_type)+', il partirait sur T'+(m.slot+1)+' ('+esc(m.head_type)+'). '+
          (under?'Le débit prévu est trop fort pour cette buse : risque de sous-extrusion.':'Réglages prévus pour une autre buse : qualité possiblement différente.')+'</div>'}).join("")+
      '<div style="margin-top:6px">Corrige : choisis pour ce filament une bobine marquée « bonne buse »'+(R.plan?', utilise le plan proposé,':'')+' ou mets la bobine dans un slot dont la tête a la bonne buse.</div>'+
      '<label><input type="checkbox" id="nozok"> Imprimer quand même avec ces buses</label></div>':"";
    var canPrint=!D.busy&&!optimizing&&!risk.length;
    if(D.engine)stats+='<div class="hint" style="margin:-6px 0 12px;opacity:.75">⚙ '+esc(D.engine)+'</div>';
    $("body").innerHTML=top+alerts+stats+table()+'<div class="row">'+recalc+'</div>'+planCard+dup+stopCard+startCard+
      '<div class="row"><button data-a="print"'+(canPrint?"":" disabled")+'>Lancer l\'impression</button>'+
      '<button class="ghost" data-a="upload"'+(risk.length?" disabled":"")+'>Envoyer sur la U1 sans lancer</button>'+
      '<button class="ghost" data-a="preflight">Ouvrir dans le Preflight multiACE</button>'+
      '<button class="ghost" data-a="close">Fermer</button></div><div id="msg"></div>'+
      (optimizing?'<p class="hint">Lancement possible une fois les bobines déplacées.</p>':'')+
      ((R.log||"").trim()?'<details><summary>Détails du moteur</summary><pre>'+esc(R.log)+'</pre></details>':'');
  }
  function choices(){var f={};Array.prototype.forEach.call(document.querySelectorAll(".pick"),function(x){if(x.dataset.v!=="auto")f[x.dataset.t]=x.dataset.v});return f}
  function closeMenus(except){Array.prototype.forEach.call(document.querySelectorAll(".menu"),function(x){if(x!==except)x.hidden=true})}
  function lock(){Array.prototype.forEach.call(document.querySelectorAll("button[data-a]"),function(x){if(x.dataset.a!=="close")x.disabled=true})}
  document.addEventListener("click",function(e){
    var pk=e.target.closest(".pk");
    if(pk){var menu=pk.parentNode.querySelector(".menu");closeMenus(menu);menu.hidden=!menu.hidden;return}
    var it=e.target.closest(".menu div[data-v]");
    if(it){
      var D=window.D,R=D.result||{},matches=R.matches||D.matches||[];
      var pick=it.closest(".pick");
      pick.dataset.v=it.dataset.v;
      pick.querySelector(".pk").innerHTML=it.innerHTML+'<span>▾</span>';
      pick.querySelector(".pk").classList.toggle("changed",it.dataset.v!==(S.forced[pick.dataset.t]||"auto"));
      Array.prototype.forEach.call(pick.querySelectorAll(".menu div"),function(x){x.classList.toggle("sel",x===it)});
      closeMenus(null);var b=document.querySelector('button[data-a="recalc"]');if(b)b.disabled=false;return;
    }
    if(!e.target.closest(".menu"))closeMenus(null);
    var btn=e.target.closest("button[data-a]");if(!btn||btn.disabled)return;
    var a=btn.dataset.a;
    if(a==="recalc"){lock();post({a:"recalc",forced:choices()});return}
    if(a==="plan-on"||a==="plan-off"){lock();post({a:"plan",on:a==="plan-on",forced:choices()});return}
    if(a==="print"&&S.armed!=="print"){S.armed="print";btn.textContent="Confirmer le lancement ?";btn.style.background="#e0a030";btn.style.color="#1b1e22";return}
    if(a==="mkspool"){var wi=btn.parentNode.querySelector(".mkw");post({a:"mkspool",ace:+btn.dataset.ace,slot:+btn.dataset.slot,weight:wi?wi.value:""});btn.disabled=true;btn.textContent="Création…";return}
    if(a==="precal"){post({a:"precal",head:+btn.dataset.head,ace:+btn.dataset.ace,slot:+btn.dataset.slot});btn.disabled=true;btn.textContent="Ajoutée à la file";return}
    S.armed=null;var msg=$("msg");if(msg){msg.className="";msg.textContent=a==="close"?"":"Envoi…"}
    if(a!=="close")lock();
    var heads=[];if(S.opt)for(var h in S.opt.heads)if(S.opt.heads[h])heads.push(+h);
    post(a==="print"||a==="upload"?{a:a,opts:S.opt?{bed:S.opt.bed,flow:S.opt.flow,cam:S.opt.cam,soft:S.opt.soft,heads:heads}:null,nozzle_ok:S.nozok}:{a:a});
  });
  document.addEventListener("change",function(e){var t=e.target;
    if(t.id==="nozok"){S.nozok=t.checked;var D=window.D||{};
      Array.prototype.forEach.call(document.querySelectorAll('button[data-a="print"],button[data-a="upload"]'),function(x){
        x.disabled=!t.checked||(x.dataset.a==="print"&&!!D.busy)});return}
    if(!S.opt)return;
    if(t.dataset.o){S.opt[t.dataset.o]=t.checked;if(t.dataset.o==="flow")render(window.D)}
    if(t.dataset.h!=null)S.opt.heads[t.dataset.h]=t.checked});
  window.orca&&window.orca.onMessage(function(m){
    if(!m)return;
    if(m.type==="data")render(m.data);
    else if(m.type==="done"){var msg=$("msg");if(msg){msg.className=m.ok?"ok":"err";msg.textContent=m.text}
      var D=window.D||{};Array.prototype.forEach.call(document.querySelectorAll("button[data-a]"),function(x){
        var blocked=((D.result||{}).nozzle_risk||[]).length&&!S.nozok&&(x.dataset.a==="print"||x.dataset.a==="upload");
        x.disabled=blocked||(x.dataset.a==="print"&&(D.busy||(m.ok&&m.final)))||x.dataset.a==="recalc"})}
  });
  render(D);
  post({a:"ready"});
})();
</script></body></html>"""


class AssignmentWindow:
    """Fenetre d'attribution : ouverte des l'export, suit les bobines en direct, verifie avant de lancer."""

    POLL = 5.0

    def __init__(self):
        self.window = None
        self.job = None              # {"id", "path", "name", "host"}
        self.forced = {}             # {filament: (ace, slot)} choisis a la main pour ce fichier
        self.mode = "loaded"
        self.meta = None
        self.data = None             # dernier etat envoye a la page
        self.result = None           # {"path", "signature", "job"}
        self._lock = threading.Lock()
        self._busy = False
        self._analyzing = threading.Lock()
        self._job_seq = 0
        self._watch_job = None

    # ---- cycle de vie
    def start(self, path, name, host, delay=1.0):
        """Nouveau fichier : ouvre (ou reutilise) la fenetre tout de suite, puis analyse en arriere-plan."""
        with self._lock:
            self._job_seq += 1
            reexport = self.job is not None and self.job.get("name") == name and self.window is not None
            self.job = {"id": self._job_seq, "path": path, "name": name, "host": host}
            self.forced, self.mode, self.meta, self.result = {}, "loaded", None, None
        banner = "Fichier réexporté : nouvelle analyse, l'ancienne est remplacée." if reexport else None
        job_id = self.job["id"]

        def worker():
            # Jamais de fenetre depuis le fil de tranchage (OrcaSlicer ne l'ouvre pas) : on attend la fin
            # de l'etape d'export, puis on ouvre depuis ce fil a part.
            time.sleep(delay)
            if not self.job or self.job["id"] != job_id:
                return
            try:
                self._send({"name": name, "loading": "Analyse du G-code en cours…", "banner": banner})
            except Exception:
                pass
            self._analyze(job_id, banner=banner)
            self._watch(job_id)

        threading.Thread(target=worker, daemon=True).start()

    def _send(self, data):
        """Met a jour la page (ou ouvre la fenetre si elle est fermee)."""
        self.data = data
        w = self.window
        if w is not None:
            try:
                if w.is_open():
                    w.post({"type": "data", "data": data})
                    return
            except Exception:
                pass
        payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
        self.window = orca.host.ui.create_window(html=ASSIGN_PAGE.replace("__DATA__", payload),
                                                 title="multiACE - Attribution des couleurs", width=900, height=760,
                                                 on_message=self.on_message, on_close=self._closed)

    def _closed(self):
        self.window = None
        self._watch_job = None

    def _reply(self, ok, text, final=False):
        w = self.window
        if w is not None:
            try:
                w.post({"type": "done", "ok": ok, "text": text, "final": final})
            except Exception:
                pass

    # ---- analyse
    def _analyze(self, job_id, banner=None, state=None):
        with self._analyzing:
            job = self.job
            if not job or job["id"] != job_id:
                return
            data = {"name": job["name"], "banner": banner}
            try:
                client = MultiAce(job["host"])
                state = state or client.state(timeout=TIMEOUT_BG)
                ps = str(state.get("printer_state") or "").lower()
                data["busy"] = ps in ("printing", "paused") or bool(state.get("swap_in_progress"))
                with open(job["path"], "r", encoding="utf-8", errors="ignore") as f:
                    gcode = f.read()
                if self.meta is None:
                    self.meta = gcode_meta(gcode)
                data["thumb"] = self.meta.get("thumb")
                weights = slot_weights(state)
                nozzle = self.meta.get("nozzle") or []
                real, _src = effective_nozzles(client)

                def htype(h):
                    if h is None:
                        return None
                    return real[h] if h < len(real) and real[h] else (nozzle[h] if h < len(nozzle) else None)
                data["slots"] = [dict(x, weight=weights.get((x["ace"], x["slot"])), head_type=htype(x["slot"]))
                                 for x in all_slots_from_state(state)]
                data["real_known"] = all(real)
                data["forced"] = {str(t): "%d_%d" % v for t, v in self.forced.items()}
                data["engine"] = prepare_engine(job["host"]).get("text")
                data["prefs"] = load_settings()["start"]
                res = analyze_gcode(gcode, state, self.mode, self.forced, self.meta, real)
                del gcode
                out = os.path.join(storage_dir(), "attribution.gcode")
                with open(out, "w", encoding="utf-8", newline="\n") as f:
                    f.write(res.pop("gcode"))
                if not self.job or self.job["id"] != job_id:
                    return          # un autre export est arrive entre-temps
                self.result = {"path": out, "signature": res["signature"], "job": job_id, "mode": res["mode"],
                               "nozzle_risk": list(res.get("nozzle_risk") or [])}
                data["result"] = res
            except AttributionError as e:
                data["error"], data["matches"] = str(e), e.matches
                data["signature"] = loadout_signature(state) if state else None
                self.result = None
            except PermissionError:
                data["error"], data["perm"] = permission_text(job["host"]), True
                self.result = None
            except Exception as e:
                data["error"] = "Erreur du moteur d'attribution : %s" % e
                self.result = None
            if self.job and self.job["id"] == job_id:
                self._send(data)

    def _watch(self, job_id):
        """Tant que la fenetre est ouverte : si les bobines changent, on recalcule ; on suit aussi l'etat d'impression."""
        if self._watch_job == job_id:
            return
        self._watch_job = job_id
        while (self.window is not None and self.job and self.job["id"] == job_id and self._watch_job == job_id
               and not _STOP.is_set()):
            if _STOP.wait(self.POLL):
                break
            try:
                state = MultiAce(self.job["host"]).state(timeout=TIMEOUT_BG)
            except Exception:
                continue
            data = self.data or {}
            known = (data.get("result") or {}).get("signature") or data.get("signature")
            sig = loadout_signature(state)
            ps = str(state.get("printer_state") or "").lower()
            busy = ps in ("printing", "paused") or bool(state.get("swap_in_progress"))
            if known is not None and sig != known and not state.get("swap_in_progress"):
                was_plan = self.mode == "optimize"
                self._analyze(job_id, banner="Les bobines ont changé : attribution recalculée.", state=state)
                res = (self.data or {}).get("result") or {}
                if was_plan and res and not res.get("plan"):
                    self.mode = "loaded"
                    self.data["banner"] = "Plan appliqué : les bobines sont à la bonne place, tu peux lancer."
                    self.data["result"]["mode"] = "loaded"
                    self._send(self.data)
            elif data and bool(data.get("busy")) != busy and not data.get("loading"):
                data["busy"] = busy
                data["banner"] = None if busy else "La U1 est libre : tu peux lancer."
                self._send(data)

    # ---- messages de la page (fil de l'interface)
    def on_message(self, m):
        if isinstance(m, str):
            try:
                m = json.loads(m)
            except ValueError:
                return
        if not isinstance(m, dict) or not self.job:
            return
        action = m.get("a")
        job_id = self.job["id"]
        if action == "ready":
            if self.data is not None and self.window is not None:
                self.window.post({"type": "data", "data": self.data})
            return
        if action == "close":
            if self.window is not None:
                self.window.close()
            return
        if action in ("recalc", "plan"):
            forced = {}
            for t, v in (m.get("forced") or {}).items():
                mm = re.fullmatch(r"(\d)_(\d)", str(v or ""))
                if mm and str(t).isdigit() and int(t) < 32:
                    forced[int(t)] = (int(mm.group(1)), int(mm.group(2)))
            self.forced = forced
            if action == "plan":
                self.mode = "optimize" if m.get("on") else "loaded"
            self._send(dict(self.data or {}, loading="Recalcul en cours…", banner=None))
            threading.Thread(target=self._analyze, args=(job_id,), daemon=True).start()
            return
        if action == "retry":
            probe_network(self.job["host"], force=True)
            self._send(dict(self.data or {}, loading="Nouvelle tentative…", banner=None))
            threading.Thread(target=self._analyze, args=(job_id,), daemon=True).start()
            return
        if action == "mkspool":
            try:
                a, sl = int(m.get("ace")), int(m.get("slot"))
                w = m.get("weight")
                w = None if w in (None, "") else int(round(float(w)))
            except (TypeError, ValueError, OverflowError):
                return
            if not (0 <= a <= 7 and 0 <= sl <= 3) or (w is not None and not 0 <= w <= 65535):
                return
            threading.Thread(target=self._make_spool, args=(job_id, a, sl, w), daemon=True).start()
            return
        if action == "precal":
            try:
                h, a, sl = int(m.get("head")), int(m.get("ace")), int(m.get("slot"))
            except (TypeError, ValueError):
                return
            if 0 <= h <= 3 and 0 <= a <= 7 and 0 <= sl <= 3:
                _PANEL._run("ACE_LOAD_HEAD", {"HEAD": h, "ACE": a, "SLOT": sl})
                _PANEL._run("ACE_PA_CALIBRATE", {"HEAD": h, "FORCE": 1})
                self._reply(True, "Calibration de ACE %d · slot %d ajoutée à la file du panneau multiACE : attends "
                                  "qu'elle soit finie avant de lancer (le PA est mémorisé sur la bobine)." % (a + 1, sl + 1))
            return
        if action in ("print", "upload", "preflight"):
            with self._lock:
                if self._busy:
                    return
                self._busy = True
            threading.Thread(target=self._send_file, args=(action, job_id, m.get("opts"), m.get("nozzle_ok") is True),
                             daemon=True).start()

    def _make_spool(self, job_id, ace, slot, weight):
        """Cree la bobine du slot dans la table multiACE (couleur, matiere, marque du slot), liee au slot."""
        host = self.job["host"]
        try:
            client = MultiAce(host)
            state = client.state(timeout=TIMEOUT_UI)
            if (state.get("spool_binding") or {}).get("%d_%d" % (ace, slot)):
                raise MultiAceError("ce slot a déjà une bobine")
            sl = next((x for x in all_slots_from_state(state) if x["ace"] == ace and x["slot"] == slot), None)
            if not sl or not sl.get("color"):
                raise MultiAceError("slot vide")
            colour = _norm_colour(sl["color"])
            if not re.fullmatch(r"#[0-9A-F]{6}", colour):
                raise MultiAceError("couleur du slot illisible")
            args = {"MATERIAL": gcode_safe(sl.get("material") or "PLA", 16).upper() or "PLA",
                    "COLOR": colour[1:], "ACE": ace, "SLOT": slot}
            for k, key in (("VENDOR", "brand"), ("SUBTYPE", "subtype")):
                v = gcode_safe(sl.get(key))
                if v:
                    args[k] = v
            if weight is not None:
                args["WEIGHT"] = weight
            client.macro("ACE_SPOOL_ADD", args, timeout=60)
            self._reply(True, "Bobine créée pour ACE %d · slot %d : tu peux maintenant la calibrer." % (ace + 1, slot + 1))
            threading.Thread(target=self._analyze, args=(job_id,), daemon=True).start()
        except PermissionError:
            self._reply(False, permission_text(host))
        except Exception as e:
            self._reply(False, "Création de la bobine : %s" % friendly_error(str(e)))

    def _prefs_file(self, res, opts):
        """Applique les choix « Au lancement » (plateau, flux, camera) au fichier attribue."""
        o = load_settings()["start"]
        heads = None
        if isinstance(opts, dict):
            o.update({k: bool(opts[k]) for k in ("bed", "flow", "cam", "soft") if k in opts})
            if isinstance(opts.get("heads"), list):
                heads = {int(h) for h in opts["heads"] if str(h).isdigit() and 0 <= int(h) <= 3}
        st = load_settings()
        st["start"] = o
        save_settings(st)
        out = os.path.join(storage_dir(), "attribution_send.gcode")
        apply_print_prefs(res["path"], out, bed_mesh=o["bed"], flow_cal=o["flow"], camera=o["cam"], heads=heads,
                          soft_start=o.get("soft", True))
        return out

    def _send_file(self, action, job_id, opts=None, nozzle_ok=False):
        job = self.job
        host = job["host"]
        base, ext = os.path.splitext(os.path.basename(job["name"]))
        try:
            client = MultiAce(host)
            if action == "preflight":
                client.send_gcode(job["path"], job["name"])
                self._reply(True, "Fichier d'origine envoyé au Preflight multiACE.")
                _POPUP.request(job["name"], origin_of(host) + "/multiace/")
                _POPUP.show_pending()
                return
            res = self.result
            if not res or res.get("job") != job_id:
                raise MultiAceError("pas de G-code attribué à jour : recalcule d'abord")
            name = base + "_multiACE" + (ext or ".gcode")
            if res.get("nozzle_risk") and not nozzle_ok:
                raise MultiAceError("filament %s sur le mauvais type de buse : corrige l'attribution, ou coche "
                                    "« imprimer quand même avec ces buses »"
                                    % ", ".join(str(t + 1) for t in res["nozzle_risk"]))
            if action == "print":
                if res.get("mode") == "optimize":
                    raise MultiAceError("déplace d'abord les bobines du plan (ou garde les bobines telles qu'elles sont)")
                state = client.state(timeout=TIMEOUT_UI)
                ps = str(state.get("printer_state") or "").lower()
                if ps in ("printing", "paused") or state.get("swap_in_progress"):
                    raise MultiAceError("la U1 est occupée (%s)" % (ps or "échange en cours"))
                if loadout_signature(state) != res["signature"]:
                    # Les bobines ont bouge depuis le calcul : on recalcule et on redemande.
                    threading.Thread(target=self._analyze, args=(job_id, "Les bobines ont changé juste avant le "
                                     "lancement : vérifie la nouvelle attribution puis relance.", state), daemon=True).start()
                    raise MultiAceError("les bobines ont changé depuis le calcul : attribution recalculée, vérifie puis relance")
                client.send_gcode(self._prefs_file(res, opts), name, endpoint="/upload-and-print")
                self._reply(True, "Impression lancée : %s" % name, final=True)
            else:
                client.upload_to_printer(self._prefs_file(res, opts), name)
                self._reply(True, "Envoyé sur la U1 (liste des fichiers) : %s" % name)
        except PermissionError:
            self._reply(False, permission_text(host))
        except Exception as e:
            self._reply(False, "Échec : %s" % e)
        finally:
            with self._lock:
                self._busy = False


_ASSIGN = AssignmentWindow()


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
        # assistant : a l'export, calculer l'attribution des couleurs aux bobines dans OrcaSlicer
        #             (fenetre de resultat) au lieu d'envoyer le fichier brut au Preflight.
        return {"also_on_print": False, "min_filaments": 1, "assistant": True}

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
        assistant = cfg.get("assistant", True)
        if to_printer and not assistant and not cfg.get("also_on_print"):
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
        # (Un vrai reexport, meme identique, relance l'analyse : la fenetre le signale.)
        if now - _recent_sends.get(key, 0) < (5 if assistant else 90):
            return orca.ExecutionResult.skipped("multiACE : deja traite")

        blocked = False
        try:
            keep_last_gcode(path, name)
            kept = True
        except PermissionError:
            kept, blocked = False, True     # OrcaSlicer a bloque la lecture : sa demande d'autorisation s'affiche
        except OSError:
            kept = False

        host = normalize_host(load_settings()["host"])
        if not host:
            try:
                host = normalize_host(ctx.config_value("print_host"))
            except Exception:
                host = ""
        if assistant:
            if not kept:
                return orca.ExecutionResult.failure(
                    orca.PluginResult.RecoverableError,
                    "multiACE : OrcaSlicer a bloque la lecture du G-code exporte. Reponds « Oui » a sa demande "
                    "d'autorisation du plugin, puis exporte a nouveau." if blocked else
                    "multiACE : copie du G-code impossible, attribution annulee")
            if not host:
                return orca.ExecutionResult.failure(orca.PluginResult.RecoverableError,
                                                    "multiACE : adresse de la U1 inconnue (onglet multiACE)")
            _recent_sends[key] = now
            _ASSIGN.start(last_gcode_paths()[0], name, host)
            if to_printer:
                # Le bouton Imprimer passe aussi par l'attribution : l'envoi direct d'OrcaSlicer est annule
                # (sinon les filaments 5+ planteraient sur la U1 et l'impression partirait sans multiACE).
                return orca.ExecutionResult.failure(
                    orca.PluginResult.FatalError,
                    "multiACE : impression prise en charge par la fenetre d'attribution multiACE "
                    "(envoi direct d'OrcaSlicer annule, c'est normal).")
            return orca.ExecutionResult.success("multiACE : attribution des couleurs en cours pour \"%s\"" % name)
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
details.opts{margin-top:8px}details.opts summary{cursor:pointer;color:var(--muted);font-size:11.5px;list-style:none}
details.opts summary::-webkit-details-marker{display:none}
details.opts[open] summary{margin-bottom:6px}details.opts .ah{margin:4px 0}
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
  <button id="rf" title="Actualiser">↻</button></div>
<div id="screenTop"></div><div id="camTop"></div>
<div id="msg" class="msg"></div><div id="queue" class="queue"></div>
<div id="mini" hidden></div>
<div id="full">
<div id="prepTop"><div id="prep"></div></div>
<div class="card" id="headsCard">
<h4 class="fh" data-fold="heads"><span><i class="chev">▾</i>Têtes<span id="headsMini" class="fmini"></span></span><button id="ua">Tout décharger</button></h4>
<div id="heads" class="heads"></div>
<div class="calib"><span>Calibration du plateau</span><select id="bt" title="Température du plateau pendant la mesure">
<option value="55" selected>55 °C</option><option value="60">60 °C</option><option value="70">70 °C</option><option value="80">80 °C</option><option value="100">100 °C</option></select>
<button data-act="calbed" title="Chauffe le plateau, attend 2 min, mesure le maillage (AUTO_BED_MESH_CALIBRATE) ; la U1 l'enregistre">Lancer</button></div>
<details class="opts"><summary>⚙ Options</summary>
<label class="ah" title="Si la U1 n'a pas fait son homing, le plugin le fait tout seul avant de charger / échanger / décharger, sans te demander."><input type="checkbox" id="ah"> Homing automatique si nécessaire</label>
<label class="ah" title="Si un ACE se déconnecte puis revient : le plugin relance son séchage là où il en était, et pendant une impression il relance la poussée du filament, uniquement pour la tête qui imprime (si multiACE ne l'a pas déjà fait)."><input type="checkbox" id="gf"> Garde-fou : relancer après une déconnexion d'ACE</label>

</details>
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
  $("gf").onchange=function(){post({command:"prefs_set",ace_guard:$("gf").checked});say($("gf").checked?"Garde-fou activé : séchage et poussée relancés si un ACE se déconnecte.":"Garde-fou désactivé.","info")};
  $("ah").onchange=function(){post({command:"prefs_set",auto_home:$("ah").checked});say($("ah").checked?"Homing automatique activé : la U1 fera son homing toute seule si besoin.":"Homing automatique désactivé : le panneau te demandera.","info")};
  window.orca&&window.orca.onMessage(function(m){
    if(!m)return;
    if(m.command==="state"){if(m.error){$("st").className="pill bad";$("st").textContent="hors ligne";say(m.error,"err");return}renderPrep(m.prep);if(S.edit){S.last=m.state||{};return}render(m.state||{})}
    else if(m.command==="prefs"){S.host=m.host||"";S.screen=m.screen||"off";S.cam=m.camera||"off";setCompact(!!m.compact);placeScreen();placeCam();S.prepPos=m.prep_pos==="bottom"?"bottom":"top";placePrep();S.fold=m.folds||{};applyFold();$("ah").checked=!!m.auto_home;$("gf").checked=m.ace_guard!==false}
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
        if cmd == "prefs_get":
            probe_network(effective_host())
            if remove_old_profile():
                self._post({"command": "done", "ok": True,
                            "text": "Ancien profil « Snapmaker U1 multiACE » supprimé (il disparaît de la liste au plus tard au prochain démarrage)."})
            st = load_settings()
            self._post({"command": "prefs", "host": effective_host(), "screen": st["screen"], "compact": st["compact"],
                        "prep_pos": st["prep_pos"], "folds": st["folds"], "camera": st["camera"],
                        "auto_home": st["auto_home"],
                        "ace_guard": st["ace_guard"], "real_nozzles": st["real_nozzles"]})
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
                self._post({"command": "state", "error": str(e)})
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
    """Plugins > "multiACE : panneau ACE" : rouvre le panneau s'il a ete ferme."""

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
