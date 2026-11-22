"""Captures de la 0.42.0 (FR et EN) : avertissement couleurs, quoi poser, tête vide au départ."""
import json, os, sys
exec(open("/home/claude/prive/test/conseil_scenario.py").read())
from playwright.sync_api import sync_playwright
OUT = "/home/claude/prive/public/shots"; os.makedirs(OUT, exist_ok=True)
def prep(dd, name):
    dd = json.loads(json.dumps(dd)); dd["version"] = "1.90"; dd["name"] = name; dd["can_queue"] = True; return dd
# 1) couleurs différentes, Optimisé propose les bonnes (cas « bleu imprimé en violet »)
exec(open("/home/claude/prive/test/couleurs_scenario.py").read().split('if __name__ == "__main__":')[0].replace("gpath = tempfile", "gpath0 = tempfile"))
D1 = prep(d, "Desk_organizer_8_colours.gcode")
# 2) quoi poser (cas de la capture : 3 bobines connues, ACE 2 non compté)
D2 = prep(d_cas1, "Desk_organizer_8_colours.gcode")
# 3) tête vide au départ
D3 = prep(d_cas2, "Desk_organizer_8_colours.gcode")
D3["load"]["heads"] = [{"idx": i, "ace": None if i == 3 else 0, "slot": None if i == 3 else i, "loaded": i != 3, "manual": False} for i in range(4)]
FAKE = """<script>window.__h=[];window.__p=[];window.orca={postMessage:function(m){window.__p.push(typeof m==="string"?JSON.parse(m):m)},onMessage:function(f){window.__h.push(f)}};</script>"""
for lang in ("fr", "en"):
    mb._LANG["v"] = lang
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path="/usr/bin/google-chrome")
        for key, dd, sel in (("couleurs", D1, ".cwarn"), ("quoi_poser", D2, ".cwarn"), ("tete_vide", D3, ".start")):
            html = mb.i18n_page(mb.U1_PAGE.replace("<head>", "<head>" + FAKE, 1).replace("__DATA__", json.dumps(dd).replace("</", "<\\/")))
            open("/home/claude/testdata/rel_%s_%s.html" % (key, lang), "w").write(html)
            pg = b.new_page(viewport={"width": 1220, "height": 1300}, device_scale_factor=2)
            pg.goto("file:///home/claude/testdata/rel_%s_%s.html" % (key, lang)); pg.wait_for_timeout(500)
            h = pg.evaluate("Math.ceil(document.querySelector('.bar').getBoundingClientRect().bottom)")
            pg.set_viewport_size({"width": 1220, "height": h}); pg.wait_for_timeout(250)
            pg.screenshot(path="%s/w_%s_%s.png" % (OUT, key, lang))
            pg.close()
        b.close()
mb._LANG["v"] = None
print("ok")
