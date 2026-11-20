"""Adresse de la U1 : boite affichee si elle est introuvable ou injoignable, correction depuis le panneau."""
import sys, types, importlib.util, tempfile, json, http.server, threading
S = tempfile.mkdtemp()
sys.modules["orca"] = types.SimpleNamespace(pages=types.SimpleNamespace(PagesPluginCapabilityBase=object),
  slicing=types.SimpleNamespace(SlicingPipelineCapabilityBase=object), script=types.SimpleNamespace(ScriptPluginCapabilityBase=object),
  base=object, plugin=lambda c: c, host=types.SimpleNamespace(plugin=types.SimpleNamespace(storage=lambda: S)))
spec = importlib.util.spec_from_file_location("mb", "/home/claude/multiace_bridge/multiace_bridge_any.py"); mb = importlib.util.module_from_spec(spec); spec.loader.exec_module(mb)
ok = lambda c, m: print(("PASS " if c else "FAIL ") + m) or (c or sys.exit(1))
class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        b = b'{"version":"test"}'; self.send_response(200); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
good = "127.0.0.1:%d" % srv.server_address[1]
c = mb.AcePanelController(); posts = []; c._post = posts.append; c._refresh = lambda: None
mb.preset_host = lambda: ""
c.on_message({"command": "set_host", "host": "pas une ip !"}); ok(posts[-1] == {"command": "host_result", "ok": False, "error": "Adresse invalide, par exemple 192.168.1.50"}, "adresse invalide refusée")
c.on_message({"command": "set_host", "host": "127.0.0.1:1"}); ok(not posts[-1]["ok"] and "Pas de multiACE" in posts[-1]["error"] and mb.load_settings()["host"] == "", "U1 qui ne répond pas : rien d'enregistré")
c.on_message({"command": "set_host", "host": "http://%s/multiace/" % good}); ok(posts[-1] == {"command": "host_result", "ok": True, "host": good} and mb.load_settings()["host"] == good, "bonne adresse vérifiée puis enregistrée")
c2 = mb.AcePanelController(); p2 = []; c2._post = p2.append
st = mb.load_settings(); st["host"] = ""; mb.save_settings(st); c2._refresh(); ok(p2 and p2[-1] == {"command": "state", "nohost": True}, "aucune adresse -> le panneau le signale")
srv.shutdown()
fake = """<script>window.__h=[];window.__p=[];window.orca={postMessage:function(m){window.__p.push(typeof m==="string"?JSON.parse(m):m)},onMessage:function(f){window.__h.push(f)}};</script>"""
open("host.html", "w").write(mb.PANEL.replace("__VERSION__", mb.VERSION).replace("<head>", "<head>" + fake, 1))
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome")
    pg = b.new_page(viewport={"width": 330, "height": 600}); pg.goto("file:///home/claude/multiace_bridge/test/host.html"); pg.wait_for_timeout(200)
    send = lambda m: pg.evaluate("m=>window.__h.forEach(f=>f(m))", m)
    send({"command": "prefs", "host": "", "screen": "off", "compact": False})
    ok(pg.is_visible("#hostbox") and "introuvable" in pg.inner_text("#hostTitle"), "pas d'adresse -> boîte affichée")
    pg.fill("#hostIn", "192.168.1.50"); pg.click("#hostOk")
    ok(pg.evaluate("window.__p.filter(m=>m.command==='set_host').pop().host") == "192.168.1.50", "Enregistrer envoie l'adresse au plugin")
    send({"command": "host_result", "ok": True, "host": "192.168.1.50"})
    ok(not pg.is_visible("#hostbox") and pg.evaluate("document.getElementById('hostCur').textContent") == "192.168.1.50", "adresse acceptée -> boîte fermée, adresse dans les options")
    send({"command": "state", "error": "U1 injoignable a 192.168.1.50 (timed out)", "unreachable": True})
    ok(pg.is_visible("#hostbox") and "ne répond pas" in pg.inner_text("#hostTitle") and pg.input_value("#hostIn") == "192.168.1.50", "U1 injoignable -> boîte pour corriger, adresse pré-remplie")
    pg.click("#hostX"); ok(not pg.is_visible("#hostbox"), "Annuler ferme la boîte")
    pg.click("#opt"); pg.click("#hostEdit"); ok(pg.is_visible("#hostbox") and "Modifier" in pg.inner_text("#hostTitle"), "Options -> Modifier l'adresse")
    send({"command": "prefs", "host": "192.168.1.50", "screen": "off", "compact": True})
    pg.click("#optX"); ok(not pg.is_visible("#optsCard"), "✕ ferme les options")
    pg.click("#hostX"); pg.click("#opt"); ok(pg.is_visible("#optsCard") and pg.is_visible("#hostEdit") and pg.is_visible("#gf"), "⚙ en haut ouvre les options, même en mode réduit")
    pg.screenshot(path="host.png")
    b.close()
print("HOST OK")
