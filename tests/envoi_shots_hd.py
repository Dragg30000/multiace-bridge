"""0.45.0 : images 2x (anglais) pour le README et Orca Cloud : en-tête + alerte, réglages de l'imprimante."""
import copy, json, sys
sys.path.insert(0, "/home/claude/prive/test")
exec(open("/home/claude/prive/test/envoi_shots.py").read().split("def page(")[0])
from playwright.sync_api import sync_playwright
OUT = sys.argv[1] if len(sys.argv) > 1 else "/home/claude/apercu/shots"
d["name"] = "Snowman_8_colours.gcode"
mb._LANG["v"] = "en"
h = mb.i18n_page(mb.U1_PAGE.replace("<head>", "<head>" + FAKE, 1).replace("__DATA__", json.dumps(d).replace("</", "<\\/")))
open("/home/claude/testdata/envoi_hd_en.html", "w").write(h)
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome")
    pg = b.new_page(viewport={"width": 1220, "height": 900}, device_scale_factor=2)
    pg.goto("file:///home/claude/testdata/envoi_hd_en.html")
    pg.click('.pr[data-plan="slicer"]')
    pg.wait_for_selector("#thumb .tl", timeout=8000)
    pg.wait_for_timeout(500)
    al = pg.locator(".alerts").bounding_box()
    pg.screenshot(path="%s/hd_preview_filament_en.png" % OUT, clip={"x": 0, "y": 0, "width": 1220, "height": al["y"] + al["height"] + 14})
    ps = pg.locator(".pset").bounding_box()
    pg.evaluate("document.querySelector('.pset').scrollIntoView({block:'center'})")
    pg.wait_for_timeout(200)
    ps = pg.locator(".pset").bounding_box()
    pg.screenshot(path="%s/hd_printer_settings_en.png" % OUT, clip={"x": ps["x"] - 14, "y": ps["y"] - 6, "width": ps["width"] + 28, "height": ps["height"] + 18})
    b.close()
mb._LANG["v"] = "fr"
print("ok")
