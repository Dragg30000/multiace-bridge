"""Camera de la U1 dans le panneau : bouton 📷 (masquee / en haut / en bas), image rafraichie, memorisation."""
import http.server, io, os, sys, threading, types, importlib.util
sys.modules["orca"] = types.SimpleNamespace(pages=types.SimpleNamespace(PagesPluginCapabilityBase=object),
  slicing=types.SimpleNamespace(SlicingPipelineCapabilityBase=object), script=types.SimpleNamespace(ScriptPluginCapabilityBase=object),
  base=object, plugin=lambda c: c)
spec = importlib.util.spec_from_file_location("mb", "/home/claude/multiace_bridge/multiace_bridge_any.py"); mb = importlib.util.module_from_spec(spec); spec.loader.exec_module(mb)
ok = lambda c, m: print(("PASS " if c else "FAIL ") + m) or (c or sys.exit(1))
from PIL import Image, ImageDraw
im = Image.new("RGB", (640, 360), (30, 34, 40)); d = ImageDraw.Draw(im); d.rectangle((200, 120, 440, 260), fill=(141, 110, 99)); d.text((20, 20), "U1 camera", fill=(255, 255, 255))
buf = io.BytesIO(); im.save(buf, "JPEG"); JPG = buf.getvalue(); hits = []
class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        hits.append(self.path)
        if self.path.startswith("/webcam/snapshot.jpg"):
            self.send_response(200); self.send_header("Content-Type", "image/jpeg"); self.send_header("Content-Length", str(len(JPG))); self.end_headers(); self.wfile.write(JPG)
        else:
            self.send_response(404); self.end_headers()
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
host = "127.0.0.1:%d" % srv.server_address[1]
fake = """<script>window.__h=[];window.__p=[];window.orca={postMessage:function(m){window.__p.push(typeof m==="string"?JSON.parse(m):m)},onMessage:function(f){window.__h.push(f)}};</script>"""
open("cam.html", "w").write(mb.PANEL.replace("__VERSION__", mb.VERSION).replace("<head>", "<head>" + fake, 1).replace("<body>", '<body style="background:#2b2d30">', 1))
st = {"aces": [], "toolheads": [], "printer_state": "printing", "device_count": 2, "display_index_base": 1}
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome")
    pg = b.new_page(viewport={"width": 330, "height": 600}); pg.goto("file://" + os.path.abspath("cam.html")); pg.wait_for_timeout(200)
    send = lambda m: pg.evaluate("m=>window.__h.forEach(f=>f(m))", m)
    send({"command": "prefs", "host": host, "screen": "off", "camera": "off", "compact": False, "folds": {}})
    send({"command": "state", "state": st})
    ok(pg.locator("#camimg").count() == 0, "masquée par défaut")
    pg.click("#cam"); pg.wait_for_timeout(1500)
    ok(pg.evaluate("document.getElementById('camimg').parentElement.parentElement.id") == "camTop", "1er clic : en haut")
    ok(pg.evaluate("document.getElementById('camimg').naturalWidth") == 640, "image de la caméra affichée")
    n = len(hits); pg.wait_for_timeout(2200)
    ok(len(hits) >= n + 1, "image rafraîchie (%d requêtes)" % (len(hits) - n))
    ok({"command": "prefs_set", "screen": "off", "camera": "top", "compact": False} in pg.evaluate("window.__p"), "choix mémorisé")
    pg.screenshot(path="v320_cam.png", clip={"x": 0, "y": 0, "width": 330, "height": 260})
    pg.click("#cam"); pg.wait_for_timeout(300)
    ok(pg.evaluate("document.getElementById('camimg').parentElement.parentElement.id") == "camBottom", "2e clic : en bas")
    pg.click("#cmp"); pg.wait_for_timeout(1200)
    ok(pg.is_visible("#camimg"), "toujours visible en mode réduit")
    pg.click("#cmp"); pg.click("#cam"); pg.wait_for_timeout(300)
    ok(pg.locator("#camimg").count() == 0, "3e clic : masquée")
    n = len(hits); pg.wait_for_timeout(1500)
    ok(len(hits) == n, "masquée : plus aucune requête")
    send({"command": "prefs", "host": "127.0.0.1:9", "screen": "off", "camera": "top", "compact": False, "folds": {}})
    pg.wait_for_timeout(1500)
    ok("Caméra indisponible" in pg.inner_text("#camTop"), "caméra injoignable : message clair")
    b.close()
srv.shutdown()
print("ALL OK")
