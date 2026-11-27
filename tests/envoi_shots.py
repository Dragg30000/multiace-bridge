"""0.45.0 : captures de la fenêtre d'envoi (aperçu repeint, filament restant, réglages de l'imprimante), FR et EN."""
import copy, json, sys
sys.path.insert(0, "/home/claude/prive/test")
import apercu_ref as R
exec(open("/home/claude/prive/test/conseil_scenario.py").read())
from playwright.sync_api import sync_playwright
OUT = sys.argv[1] if len(sys.argv) > 1 else "/home/claude/apercu/shots"
FAKE = """<script>window.__h=[];window.__p=[];window.orca={postMessage:function(m){},onMessage:function(f){window.__h.push(f)}};</script>"""
d = copy.deepcopy(d_cas2)
d["name"] = "Bonhomme_8_couleurs.gcode"
d["version"] = "1.90.1"
cols = d["report"]["slicer_colors"]
vig, _ = R.vignette_demo(["#" + c["hex"].lstrip("#")[:6] for c in cols])
d["info"]["thumb"] = R.png_data_url(vig)
slic = {m["t"]: m["slot"] for m in d["report"]["plans"]["slicer"]["mapping"] if m.get("slot")}
k0 = "%d_%d" % (slic[0]["ace"], slic[0]["slot"])
d["load"]["slots"] = {k0: {"spool": "7", "grams": 41.0, "pa": {}}}
d["printer"] = {"airprint": True, "quad": False, "refill": True, "spaghetti": True, "objects": True, "led": True, "spaghetti_sens": "high", "objects_sens": "low"}
def page(p, lang, name, scale=1):
    mb._LANG["v"] = lang
    h = mb.U1_PAGE.replace("<head>", "<head>" + FAKE, 1).replace("__DATA__", json.dumps(d).replace("</", "<\\/"))
    h = mb.i18n_page(h) if lang == "en" else h
    open("/home/claude/testdata/%s.html" % name, "w").write(h)
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome")
    pg = b.new_page(viewport={"width": 1220, "height": 900}, device_scale_factor=scale)
    pg.goto("file:///home/claude/testdata/%s.html" % name)
    if pg.locator('.pr[data-plan="slicer"]').count():
        pg.click('.pr[data-plan="slicer"]')
    pg.wait_for_selector("#thumb .tl", timeout=8000)
    pg.wait_for_timeout(500)
    return b, pg
with sync_playwright() as p:
    for lang in ("fr", "en"):
        b, pg = page(p, lang, "envoi_" + lang)
        pg.screenshot(path="%s/envoi_haut_%s.png" % (OUT, lang))
        pg.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        pg.wait_for_timeout(300)
        pg.screenshot(path="%s/envoi_bas_%s.png" % (OUT, lang))
        b.close()
    b, pg = page(p, "fr", "envoi_zoom", scale=2)
    box = pg.locator(".hd").bounding_box()
    pg.screenshot(path="%s/vignette_bobines.png" % OUT, clip={"x": box["x"], "y": box["y"], "width": 560, "height": box["height"]})
    pg.click("#thumb"); pg.wait_for_timeout(150)
    pg.screenshot(path="%s/vignette_projet.png" % OUT, clip={"x": box["x"], "y": box["y"], "width": 560, "height": box["height"]})
    b.close()
mb._LANG["v"] = "fr"
print("ok")
