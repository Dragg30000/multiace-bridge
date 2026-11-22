"""Buses lues dans la U1 (extruderN.nozzle_volume_type), repli sur la saisie « Ma U1 »."""
import http.server, json, os, sys, threading, types, importlib.util, tempfile
STORE = tempfile.mkdtemp()
sys.modules["orca"] = types.SimpleNamespace(pages=types.SimpleNamespace(PagesPluginCapabilityBase=object),
  slicing=types.SimpleNamespace(SlicingPipelineCapabilityBase=object), script=types.SimpleNamespace(ScriptPluginCapabilityBase=object),
  base=object, plugin=lambda c: c, host=types.SimpleNamespace(plugin=types.SimpleNamespace(storage=lambda: STORE)))
spec = importlib.util.spec_from_file_location("mb", "/home/claude/prive/multiace_bridge_any.py"); mb = importlib.util.module_from_spec(spec); spec.loader.exec_module(mb)
ok = lambda c, m: print(("PASS " if c else "FAIL ") + m) or (c or sys.exit(1))
HD, ST = "Haut débit", "Standard"
# reponse reelle d'une U1 (firmware avec nozzle_volume_type), champs utiles seulement
REAL = {"extruder": {"nozzle_diameter": 0.4, "nozzle_volume_type": "high_flow", "state": "PARKED"},
        "extruder1": {"nozzle_diameter": 0.4, "nozzle_volume_type": "high_flow", "state": "ACTIVATE"},
        "extruder2": {"nozzle_diameter": 0.4, "nozzle_volume_type": "standard", "state": "PARKED"},
        "extruder3": {"nozzle_diameter": 0.4, "nozzle_volume_type": "high_flow", "state": "PARKED"}}
answer = {"status": REAL}; hits = []
class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        hits.append(self.path)
        if not self.path.startswith("/printer/objects/query?extruder&extruder1&extruder2&extruder3"):
            self.send_response(404); self.end_headers(); return
        b = json.dumps({"result": {"eventtime": 1.0, "status": answer["status"]}}).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_POST(self):
        hits.append("POST " + self.path); self.send_response(405); self.end_headers()
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
host = "127.0.0.1:%d" % srv.server_address[1]
client = mb.MultiAce(host)
ok(client.head_nozzle_types() == [HD, HD, ST, HD], "lecture : T1 HD · T2 HD · T3 Standard · T4 HD")
ok(not any(h.startswith("POST") for h in hits), "lecture seule (aucun envoi à la U1)")
manual = {"v": ["", "", "", ""]}
mb.load_settings = lambda: {"real_nozzles": manual["v"]}
real, src = mb.effective_nozzles(client)
ok(real == [HD, HD, ST, HD] and src == "u1", "buses effectives = celles de la U1 (%s)" % src)
n = len(hits); mb.effective_nozzles(client)
ok(len(hits) == n, "valeur gardée 60 s : pas de nouvelle requête à chaque actualisation")
# vieux firmware : champ absent
mb._NOZZLE_CACHE.clear(); answer["status"] = {k: {"nozzle_diameter": 0.4} for k in REAL}
manual["v"] = [HD, HD, ST, HD]
real, src = mb.effective_nozzles(client)
ok(real == [HD, HD, ST, HD] and src == "manuel", "firmware sans l'info -> saisie « Ma U1 »")
# en partie
mb._NOZZLE_CACHE.clear(); answer["status"] = dict({k: {"nozzle_diameter": 0.4} for k in REAL}, extruder2={"nozzle_volume_type": "standard"})
manual["v"] = [HD, "", HD, ST]
real, src = mb.effective_nozzles(client)
ok(real == [HD, "", ST, ST] and src == "mixte", "U1 prioritaire tête par tête, saisie pour le reste : %s" % real)
# valeur inconnue (hybride) -> ignoree
mb._NOZZLE_CACHE.clear(); answer["status"] = dict(REAL, extruder3={"nozzle_volume_type": "hybrid"})
ok(client.head_nozzle_types() == [HD, HD, ST, ""], "valeur inconnue -> non devinée")
# U1 injoignable
srv.shutdown(); srv.server_close(); mb._NOZZLE_CACHE.clear()
ok(mb.MultiAce(host).head_nozzle_types() == ["", "", "", ""], "U1 injoignable -> rien d'inventé")

# panneau : buses lues dans la U1
fake = """<script>window.__h=[];window.__p=[];window.orca={postMessage:function(m){window.__p.push(typeof m==="string"?JSON.parse(m):m)},onMessage:function(f){window.__h.push(f)}};</script>"""
open("u1noz.html", "w").write(mb.PANEL.replace("__VERSION__", mb.VERSION).replace("<head>", "<head>" + fake, 1).replace("<body>", '<body style="background:#25282c">', 1))
def slot(i, col): return {"idx": i, "state": "ready" if col else "empty", "color": col, "material": "PLA" if col else "", "source": "rfid" if col else "empty"}
dragon = {"aces": [{"idx": 0, "slots": [slot(0, "#FFFFFF"), slot(1, "#8D6E63"), slot(2, None), slot(3, "#43A047")]},
                   {"idx": 1, "slots": [slot(0, None), slot(1, "#F7D959"), slot(2, "#E53935"), slot(3, "#000000")]}],
          "toolheads": [{"idx": i, "manual": False} for i in range(4)], "printer_state": "ready"}
real = [HD, HD, ST, HD]
adv = mb.slicing_advice(dragon, real, ["#8E6F64FF", "#E43A36FF", "#000000FF", "#FFFFFFFF"], [HD, HD, ST, HD])
state = json.load(open("/home/claude/src/multiACE/tests/fixtures/mock_state.json"))
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome")
    pg = b.new_page(viewport={"width": 320, "height": 700}); pg.goto("file://" + os.path.abspath("u1noz.html")); pg.wait_for_timeout(200)
    pg.evaluate("m=>window.__h.forEach(f=>f(m))", {"command": "state", "state": state, "prep": dict(adv, real=real, real_src="u1", manual=["", "", "", ""])})
    t = pg.inner_text("#prep")
    ok("T2 Standard" in t and "lues dans la U1" in t, "carte : conseils + « lues dans la U1 »")
    pg.click("text=Ma U1")
    ok("Lues dans la U1 : T1 Haut débit, T2 Haut débit, T3 Standard, T4 Haut débit" in pg.inner_text("#prep") and pg.locator("#prep select").count() == 0, "aucune saisie demandée quand la U1 répond")
    pg.screenshot(path="v260_u1.png", clip={"x": 0, "y": 0, "width": 320, "height": 260})
    b.close()
print("ALL OK")
