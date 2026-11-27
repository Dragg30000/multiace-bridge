"""0.45.0 : fenêtre d'envoi. Aperçu aux couleurs des bobines (calcul de la fenêtre = référence Python), filament
restant, réglages de l'imprimante (lecture dans la U1, commandes envoyées, fenêtre en français et en anglais)."""
import copy, json, re, sys, time
import numpy as np
sys.path.insert(0, "/home/claude/prive/test")
import apercu_ref as R
exec(open("/home/claude/prive/test/conseil_scenario.py").read())      # mb, W, d_cas2 : vrai code multiACE
from playwright.sync_api import sync_playwright


def ok(c, m):
    print(("PASS " if c else "FAIL ") + m)
    if not c:
        sys.exit(1)


FAKE = """<script>window.__h=[];window.__p=[];window.orca={postMessage:function(m){window.__p.push(typeof m==="string"?JSON.parse(m):m)},onMessage:function(f){window.__h.push(f)}};</script>"""


def url(dd, nm, en=False):
    h = mb.U1_PAGE.replace("<head>", "<head>" + FAKE, 1).replace("__DATA__", json.dumps(dd).replace("</", "<\\/"))
    open("/home/claude/testdata/%s.html" % nm, "w").write(mb.i18n_page(h) if en else h)
    return "file:///home/claude/testdata/%s.html" % nm


def launch(p):
    return p.chromium.launch(executable_path="/usr/bin/google-chrome")


# ---------------------------------------------------------------- 1. calcul de l'aperçu : fenêtre = référence
page_src = mb.U1_PAGE
a, b = page_src.index("var RPL="), page_src.index("// couleur du projet utilisée")
helpers = "\n".join(l for l in page_src.split("\n") if l.startswith("function col(") or l.startswith("function rgb("))
ok("function repaint(" in page_src[a:b] and helpers.count("function ") == 2, "code de l'aperçu trouvé dans la fenêtre")
LAB = """<html><body><script>%s
%s
window.rp=function(src,base,target){return new Promise(function(res){var im=new Image();im.onload=function(){var w=im.naturalWidth,h=im.naturalHeight,
 cv=document.createElement("canvas");cv.width=w;cv.height=h;var cx=cv.getContext("2d");cx.drawImage(im,0,0);var d=cx.getImageData(0,0,w,h),t0=performance.now();
 var r=repaint(d.data,w,h,base,target),ms=performance.now()-t0;cx.putImageData(d,0,0);res({ok:r,url:cv.toDataURL("image/png"),ms:ms})};im.src=src})};
</script></body></html>""" % (helpers, page_src[a:b])
open("/home/claude/testdata/apercu_lab.html", "w").write(LAB)


def compare(js_img, py_img, src):
    plein = src[..., 3] == 255
    d = np.abs(js_img[..., :3].astype(int) - py_img[..., :3].astype(int)).max(-1)[plein]
    return float((d <= 2).mean()), bool((js_img[..., 3] == src[..., 3]).all())


C5 = ["#000000", "#DE4343", "#F7D959", "#FFFFFF", "#61C680"]
T5 = ["#5A5A5A", "#2D6CDF", "#F28C28", "#E9DCC0", "#C0392B"]
C8 = ["#000000", "#FDD835", "#E53935", "#FFFFFF", "#8B4513", "#FB8C00", "#43A047", "#1E88E5"]
T8 = ["#222222", "#1E88E5", "#43A047", "#F5F0E6", "#FB8C00", "#8E24AA", "#E53935", "#FDD835"]
v5, vrai5 = R.vignette_demo(C5)
v8, vrai8 = R.vignette_demo(C8)
opaque = v5.copy()                                       # vignette JPG : fond plein
bgc = np.array([38, 42, 49])
af = v5[..., 3:4] / 255.0
opaque[..., :3] = (v5[..., :3] * af + bgc * (1 - af) + 0.5).astype(np.uint8)
opaque[..., 3] = 255
real = None
try:
    head = open("/home/claude/testdata/g/real.gcode", "rb").read(1 << 20).decode("utf-8", "replace")
    m = [x for x in re.finditer(r"^; thumbnail begin (\d+)x(\d+) \d+\s*\n(.*?)^; thumbnail end", head, re.M | re.S) if x.group(1) == "300"]
    if m:
        import base64, io
        from PIL import Image
        real = np.array(Image.open(io.BytesIO(base64.b64decode("".join(l.lstrip("; ").strip() for l in m[0].group(3).splitlines())))).convert("RGBA"))
except OSError:
    pass
CR = ["#000000", "#F7D959", "#DE4343", "#FFFFFF", "#61C680"]
TR = ["#5A5A5A", "#F28C28", "#2D6CDF", "#E9DCC0", "#8E44AD"]

py5, E5, _ = R.repaint(v5, C5, T5)
ok((E5[vrai5 >= 0] == vrai5[vrai5 >= 0]).mean() > 0.97, "référence : %.1f %% des pixels rattachés à la bonne couleur (5 couleurs)"
   % (100 * (E5[vrai5 >= 0] == vrai5[vrai5 >= 0]).mean()))
py8, E8, _ = R.repaint(v8, C8, T8)
ok((E8[vrai8 >= 0] == vrai8[vrai8 >= 0]).mean() > 0.95, "référence : %.1f %% (8 couleurs, petites boules comprises)"
   % (100 * (E8[vrai8 >= 0] == vrai8[vrai8 >= 0]).mean()))
same5 = R.repaint(v5, C5, C5)[0]                         # 0.46.1 : mêmes couleurs -> gris inchangés, couleurs plus vives
gris5 = np.isin(vrai5, [0, 3])
d_gris = np.abs(same5[..., :3].astype(int) - v5[..., :3].astype(int)).max(-1)[gris5]
def sat(img, sel):
    q = img[..., :3].astype(int)[sel]
    return float(np.median(q.max(-1) - q.min(-1)))
vives = [k for k in (1, 2, 4) if sat(same5, vrai5 == k) > sat(v5, vrai5 == k) + 8]
teinte = all(np.argmax(np.median(same5[..., :3][vrai5 == k], 0)) == np.argmax(np.median(v5[..., :3][vrai5 == k], 0)) for k in (1, 2, 4))
ok((d_gris <= 2).mean() > 0.99 and len(vives) == 3 and teinte,
   "référence, mêmes couleurs : noir et blanc inchangés, les 3 couleurs plus vives et de même teinte")

# 0.46.1 : un noir du projet repeint d'une couleur vive n'est plus terne (vignette sans aucune couleur vive)
yy, xx = np.mgrid[0:120, 0:120]
disque = np.zeros((120, 120, 4), np.uint8)
dd = ((xx - 60) / 46.0) ** 2 + ((yy - 62) / 30.0) ** 2 <= 1
disque[..., :3] = 47
disque[..., 3] = np.where(dd, 255, 0)
rouge = np.median(R.repaint(disque, ["#000000"], ["#E23030"])[0][..., :3][dd], 0)
ok(rouge[0] >= 140 and rouge[0] - rouge[1] >= 60, "disque noir -> bobine rouge : rouge vif %s (0.46.0 : 70, 48, 48)" % rouge.astype(int).tolist())
blanc = np.median(R.repaint(disque, ["#000000"], ["#FFFFFF"])[0][..., :3][dd], 0)
ok(blanc.min() >= 150, "disque noir -> bobine blanche : clair %s" % blanc.astype(int).tolist())
if real is not None:       # vraie vignette : un noir repeint en rouge ressemble au rouge d'origine ; un blanc repeint en noir, au noir d'Orca
    o, E, _ = R.repaint(real, CR, ["#DE4343", "#F7D959", "#DE4343", "#000000", "#61C680"])
    mk = R.masque(real)
    lab, P_ = E[mk], o[..., :3][mk].astype(float)
    ex_noir, rouge_, ex_blanc = (np.median(P_[lab == k], 0) for k in (0, 2, 3))
    noir0 = np.median(real[..., :3][mk][lab == 0].astype(float), 0)
    ok(np.abs(ex_noir - rouge_).max() <= 25 and np.abs(ex_blanc - noir0).max() <= 12,
       "vraie vignette : noir devenu rouge %s, rouge %s ; blanc devenu noir %s, noir d'Orca %s"
       % tuple(x.astype(int).tolist() for x in (ex_noir, rouge_, ex_blanc, noir0)))

with sync_playwright() as p:
    br = launch(p)
    pg = br.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto("file:///home/claude/testdata/apercu_lab.html")
    cases = [("5 couleurs", v5, C5, T5), ("8 couleurs", v8, C8, T8), ("fond plein (JPG)", opaque, C5, T5)]
    if real is not None:
        cases.append(("vraie vignette d'OrcaSlicer", real, CR, TR))
    for nom, img, base, cible in cases:
        r = pg.evaluate("([s,b,t])=>window.rp(s,b,t)", [R.png_data_url(img), base, cible])
        js = R.from_data_url(r["url"])
        py = R.repaint(img, base, cible)[0]
        frac, alpha_same = compare(js, py, img)
        ok(r["ok"] and frac >= 0.99 and alpha_same, "fenêtre = référence (%s) : %.2f %% des pixels à 2 près, transparence intacte, %d ms"
           % (nom, 100 * frac, r["ms"]))
        ok(r["ms"] < 1500, "calcul assez rapide (%s : %d ms)" % (nom, r["ms"]))
    r = pg.evaluate("([s,b,t])=>window.rp(s,b,t)", [R.png_data_url(v5), C5, C5])
    js = R.from_data_url(r["url"])
    frac, alpha_same = compare(js, same5, v5)
    ok(r["ok"] and frac >= 0.99 and alpha_same, "fenêtre = référence (mêmes couleurs) : %.2f %% des pixels à 2 près" % (100 * frac))
    r = pg.evaluate("([s,b,t])=>window.rp(s,b,t)", [R.png_data_url(disque), ["#000000"], ["#E23030"]])
    frac, alpha_same = compare(R.from_data_url(r["url"]), R.repaint(disque, ["#000000"], ["#E23030"])[0], disque)
    ok(r["ok"] and frac >= 0.99 and alpha_same, "fenêtre = référence (disque noir -> rouge) : %.2f %%" % (100 * frac))
    r = pg.evaluate("([s,b,t])=>window.rp(s,b,t)", [R.png_data_url(np.zeros((40, 40, 4), np.uint8)), C5, T5])
    ok(r["ok"] is False, "image vide : rien à peindre")
    ok(not errs, "aucune erreur JavaScript %s" % errs)
    br.close()

# ---------------------------------------------------------------- 2. aperçu dans la fenêtre d'envoi
d = copy.deepcopy(d_cas2)
cols = [c for c in d["report"]["slicer_colors"]]
vig, _ = R.vignette_demo(["#" + c["hex"].lstrip("#")[:6] for c in cols])
d["info"]["thumb"] = R.png_data_url(vig)
mb._LANG["v"] = "fr"
with sync_playwright() as p:
    br = launch(p)
    pg = br.new_page(viewport={"width": 1220, "height": 1400})
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(url(d, "envoi_apercu"))
    pg.wait_for_selector("#thumb .tl", timeout=8000)
    src0 = d["info"]["thumb"]
    pg.wait_for_function("document.querySelector('#thumb img').getAttribute('src')!==%s" % json.dumps(src0), timeout=8000)
    lab = pg.inner_text("#thumb .tl")
    s1 = pg.get_attribute("#thumb img", "src")
    rep = R.from_data_url(s1)
    plein = vig[..., 3] == 255
    chg = (np.abs(rep[..., :3].astype(int) - vig[..., :3].astype(int)).max(-1)[plein] > 6).mean()
    ok(lab == "tes bobines" and s1.startswith("data:image/png;base64,") and chg > 0.05,
       "vignette repeinte aux couleurs des bobines du plan (%s, %.0f %% des pixels changés)" % (lab, 100 * chg))
    ok("couleurs des bobines choisies" in (pg.get_attribute("#thumb", "title") or ""), "bulle d'aide sur la vignette")
    ok(pg.evaluate("getComputedStyle(document.querySelector('#thumb')).width") == "120px", "vignette agrandie (120 px)")
    pg.click("#thumb")
    pg.wait_for_timeout(80)
    ok(pg.inner_text("#thumb .tl") == "projet" and pg.get_attribute("#thumb img", "src") == src0, "clic : couleurs du projet")
    pg.click("#thumb")
    pg.wait_for_timeout(80)
    ok(pg.inner_text("#thumb .tl") == "tes bobines" and pg.get_attribute("#thumb img", "src") == s1, "second clic : de nouveau les bobines")
    # plan changé : l'aperçu suit
    plans = [k for k in ("optimize", "layer") if (d["report"]["plans"].get(k) or {}).get("feasible")]
    if plans:
        pg.click('.pr[data-plan="%s"]' % plans[0])
        pg.wait_for_timeout(600)
        ok(pg.locator("#thumb .tl").count() == 1, "autre plan : l'aperçu est recalculé (%s)" % plans[0])
    d0 = copy.deepcopy(d)
    d0["info"]["thumb"] = None
    pg.goto(url(d0, "envoi_sans_vignette"))
    pg.wait_for_timeout(300)
    ok(pg.locator("#thumb").count() == 0, "pas de vignette dans le G-code : rien")
    ok(not errs, "aucune erreur JavaScript %s" % errs)
    br.close()

# ---------------------------------------------------------------- 3. filament restant (plan « Comme tranché »)
g = [56.0, 17.0, 2.9, 3.8, 6.4, 2.0, 2.4, 2.3]
slic = {m["t"]: m["slot"] for m in d["report"]["plans"]["slicer"]["mapping"] if m.get("slot")}
k0 = "%d_%d" % (slic[0]["ace"], slic[0]["slot"])
k1 = "%d_%d" % (slic[1]["ace"], slic[1]["slot"])
need = {}
for t, s in slic.items():
    need["%d_%d" % (s["ace"], s["slot"])] = need.get("%d_%d" % (s["ace"], s["slot"]), 0) + g[t]
ts0 = [t + 1 for t, s in sorted(slic.items()) if "%d_%d" % (s["ace"], s["slot"]) == k0]
ts1 = [t + 1 for t, s in sorted(slic.items()) if "%d_%d" % (s["ace"], s["slot"]) == k1]
d3 = copy.deepcopy(d)
for p_ in d3["report"]["plans"].values():   # 0.47.0 : avec l'estimation de la U1, grammes purge comprise (vue_test) ;
    p_.pop("estimate", None)                 # ici, sans elle (multiACE avant 1.90) : grammes d'OrcaSlicer
d3["info"]["grams"] = g
d3["load"]["slots"] = {k0: {"spool": "7", "grams": need[k0] - 16, "pa": {}}}
if k1 != k0:
    d3["load"]["slots"][k1] = {"spool": "8", "grams": round(need[k1] * 1.06), "pa": {}}
for k in need:
    if k not in (k0, k1):
        d3["load"]["slots"][k] = {"spool": "9", "grams": 900.0, "pa": {}}
        break
with sync_playwright() as p:
    br = launch(p)
    pg = br.new_page(viewport={"width": 1220, "height": 1400})
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(url(d3, "envoi_filament"))
    pg.wait_for_timeout(300)
    if pg.locator('.pr[data-plan="slicer"]').count():
        pg.click('.pr[data-plan="slicer"]')
        pg.wait_for_timeout(200)
    al = pg.inner_text(".alerts") if pg.locator(".alerts").count() else ""
    w0 = "ACE %d, voie %d" % (slic[0]["ace"] + 1, slic[0]["slot"] + 1)
    ok("Pas assez de filament : " + w0 in al and "a encore %d g, il en faut environ %d g (filament %s)." % (
        round(need[k0] - 16), round(need[k0]), ", ".join(map(str, ts0))) in al, "pas assez : la voie, le poids restant et le besoin")
    if k1 != k0:
        w1 = "ACE %d, voie %d" % (slic[1]["ace"] + 1, slic[1]["slot"] + 1)
        ok("Filament juste : " + w1 in al and "sans compter la purge." in al, "juste : signalé, purge non comptée")
    ok(al.count("Pas assez de filament") + al.count("Filament juste") == (2 if k1 != k0 else 1),
       "bobine avec assez de filament ou poids inconnu : rien")
    ok(not errs, "aucune erreur JavaScript %s" % errs)
    br.close()
mb._LANG["v"] = "en"
with sync_playwright() as p:
    br = launch(p)
    pg = br.new_page(viewport={"width": 1220, "height": 1400})
    pg.goto(url(d3, "envoi_filament_en", en=True))
    pg.wait_for_timeout(400)
    if pg.locator('.pr[data-plan="slicer"]').count():
        pg.click('.pr[data-plan="slicer"]')
        pg.wait_for_timeout(300)
    al = pg.inner_text(".alerts")
    ok("Not enough filament: ACE %d, lane %d" % (slic[0]["ace"] + 1, slic[0]["slot"] + 1) in al and "g left, about" in al
       and "a encore" not in al and "voie" not in al, "traduit (%s)" % al.split("\n")[0][:90])
    br.close()
mb._LANG["v"] = "fr"

# ---------------------------------------------------------------- 4. réglages de l'imprimante : fenêtre
d4 = copy.deepcopy(d)
d4["printer"] = {"airprint": True, "quad": False, "refill": None, "spaghetti": False, "objects": True, "led": None,
                 "spaghetti_sens": "low", "objects_sens": "high"}
with sync_playwright() as p:
    br = launch(p)
    pg = br.new_page(viewport={"width": 1220, "height": 1600})
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(url(d4, "envoi_reglages"))
    pg.wait_for_timeout(300)
    ok(pg.locator(".pset").count() == 1 and pg.locator(".pset .ps").count() == 4, "4 réglages connus de la U1 affichés")
    ok(pg.is_checked("[data-ps=airprint]") and not pg.is_checked("[data-ps=quad]") and pg.is_checked("[data-ps=objects]")
       and pg.locator("[data-ps=refill]").count() == 0 and pg.locator("[data-ps=led]").count() == 0, "état lu sur la U1, inconnus cachés")
    pg.click(".pset label:has([data-ps=quad])")
    pg.wait_for_timeout(80)
    ok(pg.evaluate("window.__p")[-1] == {"a": "pset", "key": "quad", "on": True}, "clic : réglage demandé")
    ok(pg.is_disabled("[data-ps=quad]") and pg.is_checked("[data-ps=quad]") and "…" in pg.inner_text(".pset"), "en attente de la U1")
    p2 = dict(d4["printer"], quad=True)
    pg.evaluate("window.__h[0](%s)" % json.dumps({"type": "pset", "key": "quad", "ok": True, "err": None, "printer": p2}))
    pg.wait_for_timeout(80)
    ok(not pg.is_disabled("[data-ps=quad]") and pg.is_checked("[data-ps=quad]") and "✓" in pg.inner_text(".pset"), "enregistré : ✓")
    pg.click(".pset label:has([data-ps=spaghetti])")
    pg.wait_for_timeout(80)
    pg.evaluate("window.__h[0](%s)" % json.dumps({"type": "pset", "key": "spaghetti", "ok": False,
                                                  "err": "Réglage non enregistré : HTTP 500", "printer": p2}))
    pg.wait_for_timeout(80)
    ok(not pg.is_checked("[data-ps=spaghetti]") and "Réglage non enregistré : HTTP 500" in pg.inner_text(".pset"),
       "refusé par la U1 : message, case remise comme sur la U1")
    # sensibilité de la caméra (basse / haute) sous les deux détections
    ok(pg.locator(".pset .sens").count() == 2 and pg.inner_text('.sens .sg.on[data-sk=spaghetti_sens]') == "basse"
       and pg.inner_text('.sens .sg.on[data-sk=objects_sens]') == "haute", "sensibilité lue sur la U1 : spaghettis basse, objets haute")
    n0 = len(pg.evaluate("window.__p"))
    pg.click('.sens .sg[data-sk=spaghetti_sens][data-v=low]')
    pg.wait_for_timeout(60)
    ok(len(pg.evaluate("window.__p")) == n0, "niveau déjà choisi : rien n'est envoyé")
    pg.click('.sens .sg[data-sk=spaghetti_sens][data-v=high]')
    pg.wait_for_timeout(80)
    ok(pg.evaluate("window.__p")[-1] == {"a": "pset", "key": "spaghetti_sens", "value": "high"}, "clic sur « haute » : demandé")
    ok(pg.is_disabled('.sens .sg[data-sk=spaghetti_sens][data-v=low]') and pg.inner_text('.sens .sg.on[data-sk=spaghetti_sens]') == "haute",
       "en attente de la U1")
    p3 = dict(p2, spaghetti_sens="high")
    pg.evaluate("window.__h[0](%s)" % json.dumps({"type": "pset", "key": "spaghetti_sens", "ok": True, "err": None, "printer": p3}))
    pg.wait_for_timeout(80)
    ok(not pg.is_disabled('.sens .sg[data-sk=spaghetti_sens][data-v=low]') and pg.inner_text('.sens .sg.on[data-sk=spaghetti_sens]') == "haute"
       and "✓" in pg.inner_text(".sens"), "enregistré : haute ✓")
    d8 = copy.deepcopy(d4)
    d8["printer"]["objects_sens"] = None
    pg.goto(url(d8, "envoi_reglages_sans_sens"))
    pg.wait_for_timeout(250)
    ok(pg.locator(".pset .sens").count() == 1, "sensibilité inconnue de la U1 : pas de choix")
    d5 = copy.deepcopy(d)
    d5["printer"] = dict.fromkeys(("airprint", "quad", "refill", "spaghetti", "objects", "led"))
    pg.goto(url(d5, "envoi_reglages_aucun"))
    pg.wait_for_timeout(250)
    ok(pg.locator(".pset").count() == 0, "aucun réglage connu : pas de rubrique")
    d6 = copy.deepcopy(d)
    d6.pop("printer", None)
    pg.goto(url(d6, "envoi_reglages_ancien"))
    pg.wait_for_timeout(250)
    ok(pg.locator(".pset").count() == 0, "données sans réglages : pas de rubrique")
    ok(not errs, "aucune erreur JavaScript %s" % errs)
    br.close()
mb._LANG["v"] = "en"
d7 = copy.deepcopy(d)
d7["printer"] = dict({k: False for k in ("airprint", "quad", "refill", "spaghetti", "objects", "led")},
                    spaghetti_sens="low", objects_sens="low")
with sync_playwright() as p:
    br = launch(p)
    pg = br.new_page(viewport={"width": 1220, "height": 1600})
    pg.goto(url(d7, "envoi_reglages_en", en=True))
    pg.wait_for_timeout(400)
    t = pg.inner_text(".pset")
    ok("Printer settings" in t and "Turn the light off when done" in t and "U1 auto-refill" in t and "Spaghetti detection" in t
       and "Sensitivity" in t and "low" in t and "high" in t
       and not any(w in t for w in ("bobine", "Enregistrés", "Réglages", "lumière", "plateau", "Sensibilité", "basse", "haute")),
       "réglages traduits")
    pg.wait_for_selector("#thumb .tl", timeout=8000)
    pg.wait_for_function("document.querySelector('#thumb .tl').textContent!=='projet'", timeout=8000)
    ok(pg.inner_text("#thumb .tl") == "your spools", "vignette : « your spools »")
    br.close()
mb._LANG["v"] = "fr"

# ---------------------------------------------------------------- 5. réglages : lecture et commandes (Python)
ok(isinstance(d_cas2.get("printer"), dict) and set(d_cas2["printer"]) == set(mb.PSET_KEYS), "la fenêtre reçoit les réglages au chargement")


class Resp:
    def __init__(self, obj):
        self.b = json.dumps(obj).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self.b


class Opener:
    def __init__(self, status):
        self.status, self.urls = status, []

    def open(self, u, timeout=None):
        self.urls.append(u)
        if self.status is None:
            raise OSError("refusé")
        return Resp({"result": {"status": self.status}})


class FC:
    host = "192.168.1.50"

    def __init__(self, st):
        self.st = st

    def state(self, timeout=None):
        if isinstance(self.st, Exception):
            raise self.st
        return self.st


op0 = mb._OPENER
try:
    mb._OPENER = Opener({"print_task_config": {"auto_replenish_filament": True, "end_led_turn_off": False},
                         "defect_detection": {"main_enable": False, "noodle": {"enable": True, "sensitivity": "low"},
                                              "clean_bed": {"enable": False, "sensitivity": "max"}}})
    ps = mb.printer_settings(FC({"airprint_detection": True, "quad_replenish": False, "aces": []}))
    u = mb._OPENER.urls[-1]
    ok(ps == {"airprint": True, "quad": False, "refill": True, "led": False, "spaghetti": False, "objects": False,
              "spaghetti_sens": "low", "objects_sens": None},
       "lecture : multiACE + U1, caméra coupée par l'interrupteur général (%s)" % ps)
    ok(u.startswith("http://192.168.1.50/printer/objects/query?") and "print_task_config=auto_replenish_filament,end_led_turn_off" in u
       and "defect_detection" in u, "une seule requête Moonraker, via nginx")
    mb._OPENER = Opener({"defect_detection": {"main_enable": True, "noodle": {"enable": True},
                                              "clean_bed": {"enable": True, "sensitivity": "high"}}})
    ps = mb.printer_settings(FC({"aces": []}))
    ok(ps == {"airprint": None, "quad": None, "refill": None, "led": None, "spaghetti": True, "objects": True,
              "spaghetti_sens": None, "objects_sens": "high"},
       "multiACE ancien et réglages U1 absents : inconnus (%s)" % ps)
    mb._OPENER = Opener(None)
    ps = mb.printer_settings(FC(mb.MultiAceError("U1 injoignable")))
    ok(ps == dict.fromkeys(mb.PSET_KEYS), "U1 injoignable : tout inconnu, pas d'erreur")
finally:
    mb._OPENER = op0

C = mb.printer_setting_command
ok(C("airprint", True) == ("ACE_SET_AIRPRINT_DETECTION", {"ENABLE": 1}) and C("quad", False) == ("ACE_SET_QUAD_REPLENISH", {"ENABLE": 0})
   and C("refill", True) == ("SET_PRINT_PREFERENCES", {"AUTO_REPLENISH_FILAMENT": 1})
   and C("led", False) == ("SET_PRINT_PREFERENCES", {"END_LED_TURN_OFF": 0})
   and C("spaghetti", True) == ("DEFECT_DETECTION_CONFIG", {"MAIN_ENABLE": 1, "NOODLE_ENABLE": 1})
   and C("spaghetti", False) == ("DEFECT_DETECTION_CONFIG", {"NOODLE_ENABLE": 0})
   and C("objects", True) == ("DEFECT_DETECTION_CONFIG", {"MAIN_ENABLE": 1, "CLEAN_BED_ENABLE": 1})
   and C("objects", False) == ("DEFECT_DETECTION_CONFIG", {"CLEAN_BED_ENABLE": 0}) and C("rm", True) is None,
   "commandes : multiACE (ACE_SET_*) et U1 (SET_PRINT_PREFERENCES, DEFECT_DETECTION_CONFIG)")
ok(C("spaghetti_sens", "high") == ("DEFECT_DETECTION_CONFIG", {"NOODLE_SENSITIVITY": "high"})
   and C("objects_sens", "low") == ("DEFECT_DETECTION_CONFIG", {"CLEAN_BED_SENSITIVITY": "low"})
   and C("spaghetti_sens", "max") is None and C("spaghetti_sens", True) is None and C("spaghetti", "1") is None and C("led", 1) is None,
   "sensibilité : NOODLE_SENSITIVITY / CLEAN_BED_SENSITIVITY, « low » ou « high » seulement ; marche/arrêt : vrai booléen")


class FakeWin:
    def __init__(self):
        self.posts = []

    def post(self, m):
        self.posts.append(json.loads(json.dumps(m)))

    def is_open(self):
        return True


class FakeClient:
    calls, fail = [], [None]

    def __init__(self, host):
        self.host = host

    def macro(self, name, args, timeout=None):
        FakeClient.calls.append((name, args))
        if FakeClient.fail[0]:
            raise FakeClient.fail[0]


MA, PS, win0 = mb.MultiAce, mb.printer_settings, W.window
mb.MultiAce, mb.printer_settings = FakeClient, lambda c, timeout=None: {"airprint": True, "quad": True, "refill": None,
                                                                         "spaghetti": False, "objects": False, "led": False}
W.window = fw = FakeWin()
try:
    for m in ({"a": "pset", "key": "rm -rf", "on": True}, {"a": "pset", "key": "quad", "on": "1"}, {"a": "pset", "key": "quad"},
              {"a": "pset", "key": "spaghetti_sens", "value": "max"}, {"a": "pset", "key": "spaghetti_sens", "on": True},
              {"a": "pset", "key": "objects_sens", "value": "high; G28"}):
        W.on_message(m)
    time.sleep(0.3)
    ok(FakeClient.calls == [] and fw.posts == [], "clé inconnue ou valeur pas booléenne : rien n'est envoyé")
    W.on_message({"a": "pset", "key": "quad", "on": True})
    for _ in range(40):
        time.sleep(0.05)
        if fw.posts:
            break
    ok(FakeClient.calls == [("ACE_SET_QUAD_REPLENISH", {"ENABLE": 1})] and fw.posts
       and fw.posts[-1]["type"] == "pset" and fw.posts[-1]["ok"] and fw.posts[-1]["key"] == "quad" and fw.posts[-1]["printer"]["quad"] is True,
       "Quad Replenish : commande envoyée, état relu et renvoyé à la fenêtre")
    fw.posts.clear()
    W.on_message({"a": "pset", "key": "objects_sens", "value": "high"})
    for _ in range(40):
        time.sleep(0.05)
        if fw.posts:
            break
    ok(FakeClient.calls[-1] == ("DEFECT_DETECTION_CONFIG", {"CLEAN_BED_SENSITIVITY": "high"}) and fw.posts and fw.posts[-1]["ok"],
       "sensibilité des objets : commande envoyée")
    FakeClient.fail[0] = mb.MultiAceError("HTTP 500 : Unknown command")
    fw.posts.clear()
    W.on_message({"a": "pset", "key": "led", "on": True})
    for _ in range(40):
        time.sleep(0.05)
        if fw.posts:
            break
    ok(fw.posts and not fw.posts[-1]["ok"] and fw.posts[-1]["err"].startswith("Réglage non enregistré : "),
       "refusé par la U1 : la fenêtre le dit (%s)" % (fw.posts[-1]["err"] if fw.posts else ""))
finally:
    mb.MultiAce, mb.printer_settings, W.window = MA, PS, win0
    FakeClient.fail[0] = None
print("fin")
