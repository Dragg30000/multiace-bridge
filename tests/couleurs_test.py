"""0.41.2 (privée) : avertissement « couleurs différentes du projet », sans bloquer l'envoi, avec le plan Optimisé comme solution.
Vrai code multiACE de la U1 sur le cas de Dragg : projet 8 couleurs, pas de rouge, d'orange ni de bleu dans les ACE."""
import json, sys, time
exec(open("/home/claude/prive/test/couleurs_scenario.py").read().split('if __name__ == "__main__":')[0])
from playwright.sync_api import sync_playwright
def ok(c, m):
    print(("PASS " if c else "FAIL ") + m)
    if not c: sys.exit(1)
sl = {m["t"] + 1: m.get("tier") for m in d["report"]["plans"]["slicer"]["mapping"]}
ok(sl[3] == "duplicate" and sl[6] == "duplicate" and sl[8] == "name_exact",
   "code de la U1 : rouge et orange sur une bobine partagée, bleu rapproché du violet par son nom approché (%s)" % sl)
# même projet, toutes les couleurs dans les ACE
LIVE["live_slots"] = [{"ace": i // 4, "slot": i % 4, "material": "PLA", "color": (c + "ff").lower() if i % 2 else c} for i, c in enumerate(COLS)]
sent.clear(); W.start(gpath, "tout_bon.gcode", host, delay=0)
for _ in range(60):
    time.sleep(0.5)
    if sent and sent[-1].get("report"): break
d_ok = sent[-1]
FAKE = """<script>window.__h=[];window.__p=[];window.orca={postMessage:function(m){window.__p.push(typeof m==="string"?JSON.parse(m):m)},onMessage:function(f){window.__h.push(f)}};</script>"""
def page(data, name, en=False):
    h = mb.U1_PAGE.replace("<head>", "<head>" + FAKE, 1).replace("__DATA__", json.dumps(data).replace("</", "<\\/"))
    open("/home/claude/testdata/%s.html" % name, "w").write(mb.i18n_page(h) if en else h)
    return "file:///home/claude/testdata/%s.html" % name
mb._LANG["v"] = "fr"
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome"); pg = b.new_page(viewport={"width": 1220, "height": 1400})
    errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(page(d, "couleurs_t")); pg.wait_for_timeout(300)
    w = pg.inner_text(".cwarn") if pg.locator(".cwarn").count() else ""
    ok(pg.locator(".cwarn > ul li").count() == 3 and w.startswith("3 couleurs différentes du projet"), "avertissement : 3 couleurs différentes du projet")
    for line in ("Rouge (filament 3) sera imprimé en Marron (ACE 2, voie 1)", "Orange (filament 6) sera imprimé en Jaune (ACE 2, voie 2)",
                 "Bleu (filament 8) sera imprimé en Violet (ACE 1, voie 2)"):
        ok(line in w, line)
    ok(not any("(filament %d)" % n in w for n in (1, 2, 4, 5, 7)), "les filaments dans la bonne couleur ne sont pas signalés")
    ok([e.inner_text() for e in pg.query_selector_all(".pd.cw")] == ["3 couleurs différentes"],
       "nombre par plan : Comme tranché 3, Optimisé aucune (il fait poser les bonnes bobines)")
    ok("suis le plan Optimisé : il te dit où poser chaque bobine manquante, pas à pas." in w.replace("\u00a0", " ") and pg.locator("#gopt").count() == 1,
       "l'avertissement propose le plan Optimisé")
    ok("3 couleurs différentes du projet. Tu peux quand même lancer." in pg.inner_text(".bar") and not pg.is_disabled("#go"),
       "rappel près du lancement, rien n'est bloqué")
    mt = pg.inner_text("#pmap")
    ok(pg.locator("#pmap .wb").count() == 3 and all(s in mt for s in ("remplace Rouge", "remplace Orange", "remplace Bleu")),
       "carte : repère et couleur remplacée sur les 3 bobines")
    ok("filaments 3, 5" in mt and "filaments 2, 6" in mt, "carte : tous les filaments d'une bobine partagée")
    st = pg.inner_text(".start")
    ok("Jaune (remplace Orange)" in st and "Violet (remplace Bleu)" in st and "Marron (remplace Rouge)" in st, "« Au départ » : la vraie bobine et ce qu'elle remplace")
    ok(st.count("arrive pendant") == 2, "« Au départ » : une ligne par bobine qui arrive pendant l'impression (%d)" % st.count("arrive pendant"))
    pg.click("#mo"); ok(not pg.is_disabled("#up"), "envoyer sans lancer : possible"); pg.click("#mo")
    pg.click("#go"); pg.wait_for_timeout(80)
    ok(pg.evaluate("window.__p")[-1].get("a") == "print", "lancement envoyé malgré l'avertissement")
    # « Choisir le plan Optimisé » : bonnes couleurs, bobines manquantes à poser, le violet sort
    pg.goto(page(d, "couleurs_t")); pg.wait_for_timeout(300)
    pg.click("#gopt"); pg.wait_for_timeout(150)
    steps = pg.inner_text("ul.st")
    ok(pg.get_attribute("input[name=p]:checked", "value") == "optimize" and pg.locator(".cwarn").count() == 0, "clic : plan Optimisé choisi, plus d'avertissement")
    ok(steps.count("pose une bobine") == 3 and all(c in steps for c in ("Rouge", "Orange", "Bleu")), "Optimisé : bobines Rouge, Orange et Bleu à poser")
    ok("Violet" in pg.inner_text(".rm") and pg.is_disabled("#go"), "le violet est à sortir, lancement après le placement")
    # choix manuel d'une autre couleur
    pg.goto(page(d, "couleurs_t")); pg.wait_for_timeout(300)
    pg.click("#fo"); pg.click('[data-pk="3"]'); pg.wait_for_timeout(60); pg.click('[data-ch="3"][data-v="2"]'); pg.wait_for_timeout(120)
    w = pg.inner_text(".cwarn")
    ok("Blanc (filament 4) sera imprimé en Vert (ACE 1, voie 3, ton choix)" in w and pg.locator(".cwarn > ul li").count() == 4, "bobine imposée d'une autre couleur : signalée (ton choix)")
    pg.goto(page(d_ok, "couleurs_ok")); pg.wait_for_timeout(300)
    ok(pg.locator(".cwarn").count() == 0 and pg.locator(".pd.cw").count() == 0 and pg.locator("#pmap .wb").count() == 0
       and "La U1 vérifie tout avant de démarrer." in pg.inner_text(".bar"), "toutes les couleurs dans les ACE : aucun avertissement")
    ok(not errs, "aucune erreur JavaScript %s" % errs)
    b.close()
mb._LANG["v"] = "en"
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome"); pg = b.new_page(viewport={"width": 1220, "height": 1400})
    pg.goto(page(d, "couleurs_t_en", en=True)); pg.wait_for_timeout(300)
    t = pg.inner_text("body")
    ok("3 colours differ from the project" in t and "Red (filament 3) will print in Brown (ACE 2, lane 1)" in t and "replaces Orange" in t
       and "You can still start it." in t and "follow the Optimized plan" in t and "Choose the Optimized plan" in t, "avertissement traduit")
    ok(not any(x in t for x in ("remplace", "couleur", "imprimé", "lancer", "au lieu")), "plus de français dans l'avertissement anglais")
    b.close()
mb._LANG["v"] = None
print("couleurs OK")
