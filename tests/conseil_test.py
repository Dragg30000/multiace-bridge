"""0.41.4 : l'avertissement dit quoi poser et où quand « Optimisé » ne donne pas les bonnes couleurs."""
import json, sys
exec(open("/home/claude/prive/test/conseil_scenario.py").read())
from playwright.sync_api import sync_playwright
def ok(c, m):
    print(("PASS " if c else "FAIL ") + m)
    if not c: sys.exit(1)
FAKE = """<script>window.__h=[];window.__p=[];window.orca={postMessage:function(m){window.__p.push(typeof m==="string"?JSON.parse(m):m)},onMessage:function(f){window.__h.push(f)}};</script>"""
d3 = json.loads(json.dumps(d_cas2)); d3["report"]["plans"]["optimize"] = {"feasible": False, "reason": "no feasible head assignment", "mapping": []}
def url(dd, nm, en=False):
    h = mb.U1_PAGE.replace("<head>", "<head>" + FAKE, 1).replace("__DATA__", json.dumps(dd).replace("</", "<\\/"))
    open("/home/claude/testdata/%s.html" % nm, "w").write(mb.i18n_page(h) if en else h); return "file:///home/claude/testdata/%s.html" % nm
ok(not d_cas1["report"]["plans"]["optimize"]["feasible"] and d_cas1["report"]["num_aces"] == 1, "cas de la capture : la U1 ne compte que l'ACE 1, Optimisé impossible")
mb._LANG["v"] = "fr"
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome"); pg = b.new_page(viewport={"width": 1220, "height": 1400})
    errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(url(d_cas1, "conseil1")); pg.wait_for_timeout(300)
    a = pg.inner_text(".cwarn .adv")
    ok("Noir (filament 1) : pose une bobine PLA Noir en ACE 1, voie 4 (voie vide, débloque T4)" in a.replace(" ", " "), "la couleur la plus utilisée débloque la tête vide (T4)")
    ok(a.count("à la place de la bobine non identifiée") == 4 and "ACE 2, voie 4" in a, "les 4 autres couleurs à la place des bobines inconnues de l'ACE 2")
    ok("la U1 ne le compte pas" in a and "identifie-la dans le panneau" in a, "ACE non compté et bobines non identifiées expliqués")
    pg.click("#rl2"); pg.wait_for_timeout(60); ok(pg.evaluate("window.__p")[-1]["a"] == "reload", "« Recharger » depuis l'avertissement")
    pg.goto(url(d3, "conseil3")); pg.wait_for_timeout(300)
    a = pg.inner_text(".cwarn .adv").replace(" ", " ")
    ok("Bleu (filament 8) : pose une bobine PLA Bleu en ACE 1, voie 2 (à la place du Violet, qui remplace le Bleu)" in a, "voies pleines : le bleu va à la place du violet qui le remplaçait")
    ok("Rouge" in a and "Orange" in a and "à la place du Jaune" not in a and "à la place du Marron" not in a, "une bobine qui imprime aussi sa couleur n'est jamais sortie")
    pg.goto(url(d_cas2, "conseil2")); pg.wait_for_timeout(300)
    ok(pg.locator("#gopt").count() == 1 and pg.locator(".cwarn .adv").count() == 0, "Optimisé possible : il reste la solution proposée")
    ok(not errs, "aucune erreur JavaScript %s" % errs)
    b.close()
mb._LANG["v"] = "en"
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome"); pg = b.new_page(viewport={"width": 1220, "height": 1400})
    pg.goto(url(d_cas1, "conseil1_en", en=True)); pg.wait_for_timeout(300)
    a = pg.inner_text(".cwarn")
    ok("put a spool of PLA Black in ACE 1, lane 4 (empty lane, unlocks T4)" in a and "doesn’t count it" in a, "conseil traduit")
    ok(not any(w in a for w in ("pose", "voie", "bobine", "place de", "débloque")), "plus de français dans le conseil")
    b.close()
mb._LANG["v"] = None
print("conseil OK")
