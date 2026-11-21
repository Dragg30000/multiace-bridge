"""Fake `orca` module + fake multiACE server, then exercise the plugin."""
import re, http.server, json, os, sys, tempfile, threading, time, types, importlib.util, shutil

ROOT = tempfile.mkdtemp()
DATA = os.path.join(ROOT, "OrcaSlicer"); STORE = os.path.join(DATA, "orca_plugins", "storage", "multiace")
os.makedirs(STORE)
FIX = "/home/claude/src/multiACE/tests/fixtures"
sys.path.insert(0, "/home/claude/src/multiACE/multiace/web/backend")
import orca_profile

state = json.load(open(os.path.join(FIX, "mock_state.json")))
inbox = {"pending": False}
OLD = [False]
macros = []
UNLOAD_EMPTIES = [True]
overrides = []
taps = []
uploads = []
received = {}

class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def j(self, code, obj):
        b = json.dumps(obj).encode(); self.send_response(code)
        self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        if self.path == "/multiace/api/state": self.j(200, dict(state, preflight_inbox=inbox))
        elif self.path == "/multiace/api/version": self.j(200, {"web": "1.50-pre"})
        elif self.path == "/multiace/api/preflight/inbox": self.j(200, inbox)
        elif self.path.startswith("/multiace/api/orca/profile") and not OLD[0]: self.j(200, orca_profile.build_profile(state, self.path.split("=")[-1]))
        else: self.j(404, {"detail": "Not Found"})
    def do_DELETE(self):
        if self.path.startswith("/multiace/api/slot-override/"):
            overrides.append(("DEL", self.path.rsplit("/", 2)[-2:])); return self.j(200, {"ok": True})
        inbox.clear(); inbox["pending"] = False; self.j(200, {"ok": True})
    def do_POST(self):
        n = int(self.headers["Content-Length"]); body = self.rfile.read(n)
        if self.path.startswith("/screen/touch"):
            taps.append(self.path); return self.j(200, {"ok": True})
        if self.path == "/multiace/api/slot-override":
            overrides.append(json.loads(body)); return self.j(200, {"ok": True})
        if self.path == "/multiace/api/upload-and-print":
            hdr, data = body.split(b"\r\n\r\n", 1); name = hdr.decode().split('filename="')[1].split('"')[0]
            uploads.append({"name": name, "data": data}); return self.j(200, {"ok": True})
        if self.path == "/multiace/api/macro":
            m = json.loads(body); macros.append(m)
            if UNLOAD_EMPTIES[0] and m["name"] == "ACE_UNLOAD_HEAD":
                state["toolheads"][int(m["args"]["HEAD"])]["filament_detected"] = False
            if UNLOAD_EMPTIES[0] and m["name"] == "ACE_UNLOAD_ALL_HEADS":
                for t in state["toolheads"]: t["filament_detected"] = False
            if UNLOAD_EMPTIES[0] and m["name"] in ("ACE_LOAD_HEAD", "ACE_SWAP_HEAD"):
                state["toolheads"][int(m["args"]["HEAD"])]["filament_detected"] = True
            time.sleep(0.15)
            return self.j(200, {"script": "x", "result": "ok"})
        ctype = self.headers["Content-Type"]; boundary = ctype.split("boundary=")[1].encode()
        part = body.split(b"--" + boundary)[1]
        hdr, data = part.split(b"\r\n\r\n", 1); data = data[:-2]
        name = hdr.decode().split('filename="')[1].split('"')[0]
        if b"; multiACE processed:" in data[:65536]: return self.j(409, {"detail": "already processed"})
        received["name"] = name; received["data"] = data
        inbox.update(pending=True, name=name, size=len(data), ts=time.time()); self.j(200, {"ok": True, "name": name, "size": len(data)})

srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H); PORT = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()

# ---------------- fake orca
orca = types.ModuleType("orca")
class ER:
    def __init__(s, kind, status=None, msg=""): s.kind, s.status, s.msg = kind, status, msg
    def __repr__(s): return "ER(%s,%s,%r)" % (s.kind, s.status, s.msg)
orca.ExecutionResult = types.SimpleNamespace(success=lambda m="", d="": ER("success", None, m),
    skipped=lambda m="": ER("skipped", None, m), failure=lambda st, m, d="": ER("failure", st, m))
orca.PluginResult = types.SimpleNamespace(RecoverableError="Recoverable", FatalError="Fatal")
orca.LifecycleEvent = types.SimpleNamespace(PresetSelected="PresetSelected")
class CapBase:
    def __init__(s): s.posted = []; s._cfg = "{}"
    def post_message(s, m): s.posted.append(json.loads(json.dumps(m)))
    def get_config(s): return s._cfg
orca.pages = types.SimpleNamespace(PagesPluginCapabilityBase=CapBase)
orca.slicing = types.SimpleNamespace(SlicingPipelineCapabilityBase=CapBase, Step=types.SimpleNamespace(psGCodePostProcess="pp"))
orca.script = types.SimpleNamespace(ScriptPluginCapabilityBase=CapBase)
orca.base = object
orca.plugin = lambda c: c
reg = {}
orca.register_capability = lambda c: reg.setdefault("caps", []).append(c)
orca.request_permissions = lambda **k: reg.setdefault("perm", k)
class Preset:
    def __init__(s, name, file, cfg=None): s.name, s.file, s.cfg, s.is_system = name, file, cfg or {}, True
    def config_value(s, k): return s.cfg.get(k, "")
class Coll:
    def __init__(s, items): s.items = items
    def size(s): return len(s.items)
    def preset(s, i): return s.items[i]
    def find_preset(s, n): return next((p for p in s.items if p.name == n), None)
printer = Preset("Snapmaker U1 (0.4 nozzle)", os.path.join(DATA, "system", "Snapmaker", "u1.json"), {"print_host": "127.0.0.1:%d" % PORT})
user_proc = Preset("Mon process", os.path.join(DATA, "user", "12345", "process", "p.json"))
bundle = types.SimpleNamespace(printers=Coll([printer]), prints=Coll([user_proc]), filaments=Coll([]),
    current_printer_preset=lambda: printer, full_config_value=lambda k: "")
reloaded = []
orca.host = types.SimpleNamespace(plugin=types.SimpleNamespace(storage=lambda: STORE), preset_bundle=lambda: bundle,
    preset=types.SimpleNamespace(bundles=types.SimpleNamespace(reload_local=lambda i: reloaded.append(i))))
sys.modules["orca"] = orca

# load plugin from inside a fake orca_plugins dir so _data_dir() works
plugdir = os.path.join(DATA, "orca_plugins", "multiace"); os.makedirs(plugdir)
src = os.path.join(plugdir, "multiace_bridge_any.py"); shutil.copy("/home/claude/multiace_bridge/multiace_bridge_any.py", src)
spec = importlib.util.spec_from_file_location("mb", src); mb = importlib.util.module_from_spec(spec); spec.loader.exec_module(mb)

def wait(cap, n, t=5):
    end = time.time() + t
    while len(cap.posted) < n and time.time() < end: time.sleep(0.05)

ok = lambda c, m: print(("PASS " if c else "FAIL ") + m) or (c or sys.exit(1))

mb.MultiAceBridge().register_capabilities()
ok(reg["perm"]["threading"] and reg["perm"]["network"] == [], "register: threading, no host yet")

page = mb.MultiAcePage()
ok(os.path.exists(page.get_icon()) and "<html" in page.get_ui(), "icon + page")
page.on_message({"type": "init"}); wait(page, 2)
ok(page.posted[0]["type"] == "checking" and page.posted[-1] == {"type": "open", "url": "http://127.0.0.1:%d/multiace/" % PORT}, "init with preset host opens web UI")
page.posted.clear(); page.on_message({"type": "open", "host": "pas une ip !!"}); ok(page.posted[-1]["type"] == "ask", "invalid host asks again")
page.posted.clear(); page.on_message({"type": "open", "host": "127.0.0.1:1"}); ok(page.posted[-1]["type"] == "ask" and "injoignable" in page.posted[-1]["error"], "unreachable host asks again")
page.posted.clear(); page.on_message({"type": "open", "host": "http://127.0.0.1:%d/x" % PORT})
ok(page.posted[-1]["type"] == "open" and mb.load_settings()["host"] == "127.0.0.1:%d" % PORT, "manual host saved and opened")
# pipeline
gdir = tempfile.mkdtemp(); g = os.path.join(gdir, "x.gcode")
body = "; generated by OrcaSlicer\n" + "G1 X1\n" * 50000 + "T5\nG1 X2\n; filament used [mm] = 10.0,0.00,3.2,4,5.5,1.0\n"
open(g, "w").write(body)
pipe = mb.SendToPreflight(); pipe._cfg = "{}"
_st = mb.load_settings(); _st["u1_code"] = False; mb.save_settings(_st)   # ici : chemin « Preflight de multiACE » (u1code_test couvre l'autre)
mk = lambda host="File": types.SimpleNamespace(step="pp", gcode_path=g, host=host, output_name="Dragon.gcode", config_value=lambda k: "")
ok(pipe.execute(types.SimpleNamespace(step="other")).kind == "success", "non post-process step ignored")
r = pipe.execute(mk()); ok(r.kind == "success" and received["data"] == body.encode() and received["name"] == "Dragon.gcode", "export sent intact: %s" % r.msg)
ok(pipe.execute(mk()).kind == "skipped", "dedupe second run")
ok(mb.last_gcode_info()["name"] == "Dragon.gcode", "last gcode kept")
r = pipe.execute(mk("Moonraker")); ok(r.kind == "skipped", "print button: skipped by default")
pipe._cfg = json.dumps({"also_on_print": True}); mb._recent_sends.clear()
r = pipe.execute(mk("Moonraker")); ok(r.kind == "failure" and r.status == "Fatal", "also_on_print: sent then direct print stopped")
pipe._cfg = json.dumps({"min_filaments": 6}); mb._recent_sends.clear()
r = pipe.execute(mk()); ok(r.kind == "skipped" and "5 filament" in r.msg, "min_filaments: " + r.msg)
pipe._cfg = "{}"; mb._recent_sends.clear()
open(g, "w").write("; multiACE processed: yes\n" + body); ok(pipe.execute(mk()).kind == "skipped", "already processed file not sent")
open(g, "w").write(body + "; u1control: print setup done\n"); r = pipe.execute(mk()); ok(r.kind == "failure" and r.status == "Recoverable", "u1control-modified file refused")
open(g, "w").write(body)
os.rename(mb._settings_path(), mb._settings_path() + ".bak")
r = pipe.execute(mk()); ok(r.kind == "failure" and "inconnue" in r.msg, "no host -> recoverable error: " + r.msg[:70])
os.rename(mb._settings_path() + ".bak", mb._settings_path())

r = mb.ResendLast().execute(); ok(r.kind == "success", "resend script: " + r.msg)

# dock panel
panels = []
class FakePanel:
    def __init__(s, **k): s.k = k; s.posts = []; s.open = True; s.hidden = False; panels.append(s)
    def hide(s): s.hidden = True
    def post(s, d): s.posts.append(json.loads(json.dumps(d)))
    def is_open(s): return s.open
    def show(s): s.hidden = False
notes = []
orca.host.ui = types.SimpleNamespace(create_dock_panel=lambda **k: FakePanel(**k), ImportantNotificationLevel="Important",
                                     push_notification=lambda lvl, txt, hyper="", cb=None: notes.append((lvl, txt, hyper, cb)))
mb.auto_open_panel()
ok(len(panels) == 1 and panels[0].k["dock"] == "right", "panel auto-opened docked right")
mb.auto_open_panel(); ok(len(panels) == 1, "auto-open only once")
ok(mb.AcePanel().execute().msg.startswith("Panneau ACE affiche"), "script reuses panel")
mb._PANEL.on_close(); mb.auto_open_panel(); ok(len(panels) == 1, "no auto-reopen after user closed it")
ok(mb.AcePanel().execute().kind == "success" and len(panels) == 2, "script reopens after close")
panels.pop(0); ap = mb._PANEL
P = panels[0]
mb.UNLOAD_SETTLE, mb.UNLOAD_POLL = 0.3, 0.1
def LD():
    d = [x for x in P.posts if x.get("command") == "done"]
    return d[-1] if d else {}
ap.on_message({"command": "refresh"}); time.sleep(0.5)
ok(P.posts and P.posts[-1]["command"] == "state" and "aces" in P.posts[-1]["state"], "panel state")
state["printer_state"] = "ready"
ap.on_message({"command": "load", "head": 2, "ace": 1, "slot": 2}); time.sleep(0.5)
ok(macros[-1] == {"name": "ACE_SWAP_HEAD", "args": {"HEAD": 2, "ACE": 1, "SLOT": 2}} and LD()["ok"], "queued load on an occupied head becomes a swap")
# --- file d'attente : enchainement dans l'ordre, pause au premier echec, reprise, retrait
macros.clear(); state["toolheads"][1]["filament_detected"] = False; UNLOAD_EMPTIES[0] = True
ap.on_message({"command": "unload", "head": 3}); ap.on_message({"command": "load", "head": 1, "ace": 0, "slot": 1}); ap.on_message({"command": "unload", "head": 2})
time.sleep(0.05)
q = [x for x in P.posts if x.get("command") == "queue"][-1]
ok(len(q["items"]) >= 2, "several actions queued while one runs: %s" % [i["label"] for i in q["items"]])
time.sleep(2.0)
ok([m["name"] for m in macros] == ["ACE_UNLOAD_HEAD", "ACE_LOAD_HEAD", "ACE_UNLOAD_HEAD"] and [m["args"].get("HEAD") for m in macros] == [3, 1, 2], "queue runs in click order (empty head -> load): %s" % macros)
ok([x for x in P.posts if x.get("command") == "queue"][-1]["items"] == [], "queue empty at the end")
macros.clear(); state["toolheads"][3]["filament_detected"] = True
ap.on_message({"command": "unload", "head": 3}); ap.on_message({"command": "dry", "ace": 1, "temp": 50, "duration": 240}); time.sleep(0.05)
q = [x for x in P.posts if x.get("command") == "queue"][-1]
ok([i["label"] for i in q["items"]][-1].startswith("Séchage ACE 2"), "drying goes into the queue: %s" % [i["label"] for i in q["items"]])
time.sleep(1.2)
ok([m["name"] for m in macros] == ["ACE_UNLOAD_HEAD", "ACE_DRY"], "drying runs after the queued unload: %s" % macros)
macros.clear(); state["toolheads"][1].update(filament_detected=True, ace=0, slot=1)
ap.on_message({"command": "calib_pa", "head": 1, "ace": 0, "slot": 1}); time.sleep(1.0)
ok([m["name"] for m in macros] == ["ACE_PA_CALIBRATE"] and macros[0]["args"] == {"HEAD": 1, "FORCE": 1}, "PA calibration: spool already on its head -> load skipped, forced measure: %s" % macros)
macros.clear(); state["toolheads"][2].update(filament_detected=False, ace=None, slot=None)
ap.on_message({"command": "calib_pa", "head": 2, "ace": 1, "slot": 2}); time.sleep(1.2)
ok([m["name"] for m in macros] == ["ACE_LOAD_HEAD", "ACE_PA_CALIBRATE"], "PA calibration: loads the chosen spool first: %s" % macros)
macros.clear(); ap.on_message({"command": "calib_bed", "temp": 60}); ap.on_message({"command": "calib_bed", "temp": 200}); time.sleep(0.8)
ok(macros == [{"name": "AUTO_BED_MESH_CALIBRATE", "args": {"TEMP": 60}}], "bed calibration queued, absurd temp ignored: %s" % macros)
ok(mb.action_label("AUTO_BED_MESH_CALIBRATE", {"TEMP": 60}) == "Calibration du plateau (60 °C)" and mb.action_label("ACE_PA_CALIBRATE", {"HEAD": 1, "FORCE": 1}) == "Calibration du filament (PA) sur T2", "calibration labels")
pass
for i in range(4): state["toolheads"][i]["filament_detected"] = True
mb.QUEUE_POLL = 0.1; macros.clear(); state["swap_in_progress"] = True
ap.on_message({"command": "unload", "head": 3}); time.sleep(0.5)
ok(macros == [], "queued action waits while multiACE is swapping")
state["swap_in_progress"] = False; time.sleep(0.6)
ok(macros and macros[-1]["name"] == "ACE_UNLOAD_HEAD", "then runs when the swap is over")
state["toolheads"][3]["filament_detected"] = True
macros.clear(); state["printer_state"] = "busy"
ap.on_message({"command": "unload", "head": 3}); time.sleep(0.5)
ok(macros == [], "queued action waits while the U1 is busy")
state["printer_state"] = "ready"; time.sleep(0.6)
ok(macros and macros[-1]["name"] == "ACE_UNLOAD_HEAD", "then runs when the U1 is free")
state["toolheads"][3]["filament_detected"] = True

ap.on_message({"command": "swap", "head": 0, "ace": 1, "slot": 0}); time.sleep(0.5)
ok(macros[-1] == {"name": "ACE_SWAP_HEAD", "args": {"HEAD": 0, "ACE": 1, "SLOT": 0}}, "swap -> ACE_SWAP_HEAD")
ap.on_message({"command": "unload", "head": 0}); time.sleep(0.5)
ok(macros[-1] == {"name": "ACE_UNLOAD_HEAD", "args": {"HEAD": 0}}, "unload -> ACE_UNLOAD_HEAD")
ap.on_message({"command": "unload_all"}); time.sleep(0.5)
ok(macros[-1]["name"] == "ACE_UNLOAD_ALL_HEADS", "unload all")
n0 = len(macros); ap.on_message({"command": "unload", "head": 9}); ap.on_message({"command": "load", "head": 1, "ace": "x", "slot": 1}); time.sleep(0.3)
ok(len(macros) == n0, "bad args ignored")
ap.on_message({"command": "dry", "ace": 1, "temp": 50, "duration": 240}); time.sleep(0.5)
ok(macros[-1] == {"name": "ACE_DRY", "args": {"ACE": 1, "TEMP": 50, "DURATION": 240}}, "dry -> ACE_DRY")
n1 = len(macros); ap.on_message({"command": "dry", "ace": 1, "temp": 90, "duration": 240}); time.sleep(0.3); ok(len(macros) == n1, "dry temp >55 refused")
state["printer_state"] = "printing"
ap.on_message({"command": "dry", "ace": 0, "temp": 45, "duration": 120}); time.sleep(0.5); ok(macros[-1]["name"] == "ACE_DRY" and macros[-1]["args"]["ACE"] == 0, "dry allowed while printing (like web UI)")
ap.on_message({"command": "stopdry", "ace": 0}); time.sleep(0.5)
ok(macros[-1] == {"name": "ACE_STOP_DRYING", "args": {"ACE": 0}}, "stop drying allowed while printing")
n0 = len(macros); ap.on_message({"command": "unload", "head": 0}); time.sleep(0.5)
ok(len(macros) == n0 and not LD()["ok"] and "impression" in LD()["text"], "refused while printing")
ap.on_message({"command": "unload", "head": 1}); time.sleep(0.4)
q = [x for x in P.posts if x.get("command") == "queue"][-1]
ok(q["paused"] and len(q["items"]) == 2 and len(macros) == n0, "queue paused after a failure, next action waits")
ap.on_message({"command": "queue_remove", "id": q["items"][1]["id"]}); time.sleep(0.2)
q = [x for x in P.posts if x.get("command") == "queue"][-1]
ok(len(q["items"]) == 1 and q["paused"], "remove a waiting action")
state["printer_state"] = "ready"; state["toolheads"][0]["filament_detected"] = True; ap.on_message({"command": "queue_resume"}); time.sleep(0.6)
ok(macros[-1] == {"name": "ACE_UNLOAD_HEAD", "args": {"HEAD": 0}} and [x for x in P.posts if x.get("command") == "queue"][-1]["items"] == [], "resume runs the failed action")
ap.on_message({"command": "unload", "head": 0}); ap.on_message({"command": "queue_clear"}); time.sleep(0.4)
state["printer_state"] = "printing"
macros.clear()
ap.on_message({"command": "edit", "ace": 0, "slot": 0, "color": "#E53935", "material": "petg", "brand": "SUNLU", "subtype": "Matte;#x", "weight": "512.4", "apply_spool": True}); time.sleep(0.6)
ok(overrides[-1] == {"ace": 0, "slot": 0, "material": "PETG", "brand": "SUNLU", "subtype": "Mattex", "color": "#e53935"}, "edit -> slot override (sanitized), even while printing")
ok(macros[0] == {"name": "ACE_SPOOL_SET", "args": {"ID": "6", "MATERIAL": "PETG", "COLOR": "E53935", "SUBTYPE": "Mattex", "VENDOR": "SUNLU", "WEIGHT": 512}}, "edit -> ACE_SPOOL_SET on bound spool")
ok(macros[-1]["name"] == "MULTIACE_REFRESH_OVERRIDES", "overrides refreshed")
macros.clear(); ap.on_message({"command": "edit", "ace": 0, "slot": 0, "color": "#000000", "material": "PLA", "weight": "800", "apply_spool": False}); time.sleep(0.6)
ok(macros[0] == {"name": "ACE_SPOOL_SET", "args": {"ID": "6", "WEIGHT": 800}}, "weight only when spool write-back off")
# --- bobine sans RFID : associer / creer / detacher
macros.clear(); ap.on_message({"command": "edit", "ace": 0, "slot": 0, "color": "#112233", "material": "PLA", "weight": "750", "apply_spool": True, "spool": "3"}); time.sleep(0.6)
ok(macros[0] == {"name": "ACE_SPOOL_ASSIGN", "args": {"ACE": 0, "SLOT": 0, "ID": "3"}} and macros[1]["name"] == "ACE_SPOOL_SET" and macros[1]["args"]["ID"] == "3" and macros[1]["args"]["WEIGHT"] == 750, "edit -> assign another spool then update it: %s" % macros[:2])
macros.clear(); ap.on_message({"command": "edit", "ace": 1, "slot": 3, "color": "#ff8da1", "material": "PLA", "brand": "SUNLU", "weight": "1000", "spool": "new"}); time.sleep(0.6)
ok(macros[0] == {"name": "ACE_SPOOL_ADD", "args": {"MATERIAL": "PLA", "COLOR": "FF8DA1", "ACE": 1, "SLOT": 3, "VENDOR": "SUNLU", "WEIGHT": 1000}}, "edit -> new spool bound to the slot: %s" % macros[:1])
macros.clear(); ap.on_message({"command": "edit", "ace": 0, "slot": 0, "color": "#112233", "material": "PLA", "spool": ""}); time.sleep(0.6)
ok(macros[0] == {"name": "ACE_SPOOL_ASSIGN", "args": {"ACE": 0, "SLOT": 0}} and all(m["name"] != "ACE_SPOOL_SET" for m in macros), "edit -> detach spool: %s" % macros)
macros.clear(); ap.on_message({"command": "edit", "ace": 0, "slot": 0, "color": "#112233", "material": "PLA", "spool": "x1"}); time.sleep(0.3)
ok(macros == [], "bad spool id refused")
macros.clear(); ap.on_message({"command": "edit", "ace": 0, "slot": 2, "color": "#00ff00", "material": "PLA", "weight": "800"}); time.sleep(0.6)
ok([m["name"] for m in macros] == ["MULTIACE_REFRESH_OVERRIDES"], "unbound slot: no spool write")
n2 = len(overrides); ap.on_message({"command": "edit", "ace": 0, "slot": 0, "color": "red"}); time.sleep(0.3); ok(len(overrides) == n2, "bad colour refused")
ap.on_message({"command": "reset", "ace": 1, "slot": 2}); time.sleep(0.5)
ok(overrides[-1] == ("DEL", ["1", "2"]) and macros[-1]["name"] == "MULTIACE_REFRESH_OVERRIDES", "reset -> DELETE override")
state["printer_state"] = "ready"
# prefs, hide, tap
ap.on_message({"command": "prefs_set", "screen": "bottom", "compact": True})
ok(mb.load_settings()["screen"] == "bottom" and mb.load_settings()["compact"] is True, "prefs saved")
P.posts.clear(); ap.on_message({"command": "prefs_get"}); ok(P.posts[-1] == {"command": "prefs", "host": "127.0.0.1:%d" % PORT, "screen": "bottom", "compact": True, "prep_pos": "top", "folds": {}, "camera": "off", "auto_home": False, "ace_guard": True, "u1_code": False, "real_nozzles": ["", "", "", ""], "auto_pipeline": True, "lang": "auto", "lang_now": mb.ui_lang()}, "prefs sent")
ap.on_message({"command": "prefs_set", "screen": "sideways"}); ok(mb.load_settings()["screen"] == "bottom", "bad screen value ignored")
ap.on_message({"command": "hide"}); ok(P.hidden and notes and notes[-1][2] == "Afficher", "hide -> panel hidden + notification")
ok(notes[-1][3]() is True and not P.hidden, "notification link shows panel again")
ap.on_message({"command": "tap", "x": 120, "y": 300}); time.sleep(0.4); ok(taps[-1] == "/screen/touch?a=tap&x=120&y=300", "tap forwarded to U1 screen")
n3 = len(taps); ap.on_message({"command": "tap", "x": -1, "y": 3}); time.sleep(0.2); ok(len(taps) == n3, "bad tap ignored")

# preflight popup after export
wins = []
class FakeWin:
    def __init__(s, **k): s.k = k; s.open = True; s.posts = []; wins.append(s)
    def post(s, d): s.posts.append(json.loads(json.dumps(d)))
    def is_open(s): return s.open
    def close(s): s.open = False
import threading as _th
WIN_ON_CALLER = []
def _cw(**k):
    if _th.current_thread() is _th.main_thread() and "Attribution" in str(k.get("title", "")):
        WIN_ON_CALLER.append(k.get("title"))
    return FakeWin(**k)
orca.host.ui.create_window = _cw
orca.LifecycleEvent.GCodeExportFinished = "GCodeExportFinished"
mb._recent_sends.clear(); open(g, "w").write(body)
r = pipe.execute(mk()); ok(r.kind == "success", "export sent")
page.on_lifecycle_event("GCodeExportFinished", types.SimpleNamespace(msg=""))
ok(len(wins) == 1 and "http://127.0.0.1:%d/multiace/" % PORT in wins[0].k["html"] and "Dragon.gcode" in wins[0].k["html"], "popup opened on export finished")
time.sleep(3); ok(len(wins) == 1, "fallback does not open a second popup")
mb._recent_sends.clear(); r = pipe.execute(mk()); time.sleep(3)
ok(len(wins) == 2 and not wins[0].open, "fallback opens popup and replaces the old one")
mb._recent_sends.clear(); pipe._cfg = json.dumps({"also_on_print": True}); pipe.execute(mk("Moonraker")); time.sleep(3)
ok(len(wins) == 2, "no popup for direct print"); pipe._cfg = "{}"

# export -> original file to the multiACE Preflight inbox (no attribution in the plugin)
mb._recent_sends.clear(); pipe._cfg = "{}"; inbox["pending"] = False; received.clear()
r = pipe.execute(mk()); time.sleep(0.5)
ok(r.kind == "success" and inbox.get("pending") and b"ACE_SWAP_HEAD" not in received["data"], "export -> ORIGINAL G-code sent to the Preflight inbox: " + r.msg)

# permission error mapping
import urllib.error
c = mb.MultiAce("127.0.0.1:1")
orig = mb._OPENER.open
mb._OPENER.open = lambda *a, **k: (_ for _ in ()).throw(urllib.error.URLError(PermissionError("denied")))
try: c.state(); ok(False, "perm")
except PermissionError: ok(True, "audit PermissionError surfaces through URLError")
mb._OPENER.open = orig
try: mb.MultiAce("127.0.0.1:1").state(timeout=1); ok(False, "x")
except mb.MultiAceError as e: ok("injoignable" in str(e), "offline -> readable error")
# 0.34 : le plugin demarre au chargement, sans passer par l'onglet multiACE
mb._PANEL.panel = None; mb._PANEL.closed_by_user = False
mb.AcePanel().on_load()
ok(mb._PANEL.panel is not None, "panneau ouvert au chargement du plugin (sans l'onglet multiACE)")
print("ALL OK")
