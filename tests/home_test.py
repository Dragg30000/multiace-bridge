import sys, types, tempfile, importlib.util, json
S = tempfile.mkdtemp()
sys.modules["orca"] = types.SimpleNamespace(pages=types.SimpleNamespace(PagesPluginCapabilityBase=object), slicing=types.SimpleNamespace(SlicingPipelineCapabilityBase=object), script=types.SimpleNamespace(ScriptPluginCapabilityBase=object), base=object, plugin=lambda c: c, host=types.SimpleNamespace(plugin=types.SimpleNamespace(storage=lambda: S)))
sp = importlib.util.spec_from_file_location("mb", "/home/claude/prive/multiace_bridge_any.py"); mb = importlib.util.module_from_spec(sp); sp.loader.exec_module(mb)
body = json.dumps({"detail": json.dumps({"error": {"code": 400, "message": "Must home Z axis first: 44.200 250.000 277.000 [-10.000]", "traceback": "Traceback (most recent call last):\n File x"}})})
m = mb.error_message(body); print(m)
assert m.startswith("Must home Z axis first") and "Traceback" not in m
assert mb.needs_home(m) and "homing" in mb.friendly_error(m)
b2 = '{"error": {"code": 400, "message": "Must home Z axis first", "traceback": "Traceback..."}}'
assert mb.error_message(b2) == "Must home Z axis first"
print("HOME OK")

# --- bout a bout : fausse U1 (multiACE + Moonraker 7125) non referencee
import http.server, threading, time
ST = {"homed": "", "g28": 0, "macros": [], "detected": [True, True, True, True]}
class MA(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _j(self, code, obj):
        b = json.dumps(obj).encode(); self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        if self.path.startswith("/multiace/api/state"):
            self._j(200, {"printer_state": "ready", "toolheads": [{"filament_detected": d} for d in ST["detected"]], "aces": []})
        elif self.path.startswith("/printer/objects/query"):
            self._j(200, {"result": {"status": {"toolhead": {"homed_axes": ST["homed"]}}}})
        else: self._j(404, {})
    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0); body = self.rfile.read(n)
        if self.path == "/server/files/upload":
            ST["upload"] = body; self._j(201, {"result": {"item": {"path": "x.gcode"}}}); return
        if self.path.startswith("/printer/gcode/script"):
            raise SystemExit("port 7125 / gcode script must not be used")
        elif self.path == "/multiace/api/macro":
            m = json.loads(body)
            if m["name"] == "G28":
                ST["g28"] += 1; ST["homed"] = "xyz"; self._j(200, {"result": "ok"}); return
            ST["macros"].append(m["name"])
            if not ST["homed"]:
                self._j(400, {"detail": json.dumps({"error": {"code": 400, "message": "Must home Z axis first: 1 2 3", "traceback": "Traceback..."}})}); return
            if m["name"] == "ACE_UNLOAD_ALL_HEADS": ST["detected"] = [False] * 4
            self._j(200, {"ok": True})
        else: self._j(404, {})
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 7125), MA); threading.Thread(target=srv.serve_forever, daemon=True).start()
mb.effective_host = lambda: "127.0.0.1:7125"
mb.MultiAce.__init__.__defaults__
class P:
    posts = []
    def post(self, d): self.posts.append(json.loads(json.dumps(d)))
mb.UNLOAD_SETTLE, mb.UNLOAD_POLL = 0.5, 0.1
pc = mb.AcePanelController(); win = P(); pc._post = win.post
def last():
    d = [x for x in win.posts if x.get("command") == "done"]
    return d[-1]
def settle():
    time.sleep(0.2); end = time.time() + 8
    while (pc._qrun or pc._action) and time.time() < end: time.sleep(0.05)
    time.sleep(0.2)
pc.on_message({"command": "swap", "head": 0, "ace": 0, "slot": 0}); settle()
assert last().get("fix") == "home" and ST["macros"] == [], last()          # pre-check : rien envoye
print(last()["text"])
pc.on_message({"command": "home", "retry": True}); settle()
assert ST["g28"] == 1 and ST["macros"] == ["ACE_SWAP_HEAD"] and last()["ok"], (ST, last())
print([p.get("text") for p in win.posts[-3:]])
# unload_all qui laisse du filament detecte -> pas de faux "Termine"
ST["detected"] = [True] * 4
pc._run("ACE_UNLOAD_HEAD", {"HEAD": 1}); settle()
assert last()["ok"] and "capteur de T2 indique encore" in last()["text"], last()   # avertissement, file non bloquee
# capteur qui se met a jour avec retard : pas d'avertissement
ST["detected"] = [True] * 4; ST["slow_clear"] = True
threading.Timer(0.25, lambda: ST["detected"].__setitem__(2, False)).start()
pc._run("ACE_UNLOAD_HEAD", {"HEAD": 2}); settle()
assert last()["ok"] and last()["text"] == "Terminé : Déchargement T3", last()
pc.on_message({"command": "queue_clear"}); settle()
pc._run("ACE_UNLOAD_ALL_HEADS", {}); settle()
assert last()["ok"], last()
# moonraker absent du pre-check (None) -> on envoie quand meme, et l'erreur reste propre
ST["homed"] = ""; orig = mb.MultiAce.homed_axes; mb.MultiAce.homed_axes = lambda self, timeout=1: None
ST["detected"] = [False] * 4
pc._run("ACE_LOAD_HEAD", {"HEAD": 0, "ACE": 0, "SLOT": 1}); settle()
assert last().get("fix") == "home" and "Traceback" not in last()["text"] and "homing" in last()["text"], last()
print(last()["text"])
import os
tmp = os.path.join(S, "t.gcode"); open(tmp, "w").write("G1 X1\n")
mb.MultiAce("127.0.0.1:7125").upload_to_printer(tmp, "t.gcode")
assert b'name="root"' in ST["upload"] and b"G1 X1" in ST["upload"], "upload via nginx /server/files/upload"
# --- homing automatique
mb.MultiAce.homed_axes = orig
_ls = mb.load_settings
mb.load_settings = lambda: dict(_ls(), auto_home=True)
pc.on_message({"command": "queue_clear"}); settle()
ST["homed"] = ""; ST["detected"] = [False] * 4; g0 = ST["g28"]; n0 = len(ST["macros"])
pc._run("ACE_LOAD_HEAD", {"HEAD": 1, "ACE": 0, "SLOT": 2}); settle()
assert ST["g28"] == g0 + 1 and ST["macros"][n0:] == ["ACE_LOAD_HEAD"] and last()["ok"] and "homing automatique" in last()["text"], (ST, last())
assert any("Homing automatique" in (p.get("text") or "") for p in win.posts if p.get("command") == "status")
# verification impossible (None) + refus Klipper -> homing auto puis un seul nouvel essai
ST["homed"] = ""; ST["detected"] = [False] * 4; g0 = ST["g28"]; mb.MultiAce.homed_axes = lambda self, timeout=1: None
pc._run("ACE_LOAD_HEAD", {"HEAD": 2, "ACE": 0, "SLOT": 3}); settle()
assert ST["g28"] == g0 + 1 and last()["ok"], (ST, last())
mb.MultiAce.homed_axes = orig
# pendant une impression : jamais de homing automatique
mb.load_settings = _ls
print("AUTO HOME OK")
print("HOME E2E OK"); srv.shutdown()
