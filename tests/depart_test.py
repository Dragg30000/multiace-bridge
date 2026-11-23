"""0.42.0 : tête vide au départ (proposer de la charger), éditeur de bobine (bobine notée ailleurs),
« Optimisé » impossible à cause des bobines chargées (proposition de disposition de la U1)."""
import json, sys, time, types
exec(open("/home/claude/prive/test/conseil_scenario.py").read())
from playwright.sync_api import sync_playwright
def ok(c, m):
    print(("PASS " if c else "FAIL ") + m)
    if not c: sys.exit(1)
FAKE = """<script>window.__h=[];window.__p=[];window.orca={postMessage:function(m){window.__p.push(typeof m==="string"?JSON.parse(m):m)},onMessage:function(f){window.__h.push(f)}};</script>"""
def url(dd, nm, en=False):
    h = mb.U1_PAGE.replace("<head>", "<head>" + FAKE, 1).replace("__DATA__", json.dumps(dd).replace("</", "<\\/"))
    open("/home/claude/testdata/%s.html" % nm, "w").write(mb.i18n_page(h) if en else h); return "file:///home/claude/testdata/%s.html" % nm

# --- 1. tête vide au départ (cas du 22/11 : T4 vide, alimentée par ACE 2 voie 4)
d = json.loads(json.dumps(d_cas2))
sl = {m["t"]: m["slot"] for m in d["report"]["plans"]["slicer"]["mapping"] if m.get("slot")}
d["load"]["heads"] = [{"idx": i, "ace": None if i == 3 else 0, "slot": None if i == 3 else i, "loaded": i != 3, "manual": False} for i in range(4)]
mb._LANG["v"] = "fr"
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome"); pg = b.new_page(viewport={"width": 1220, "height": 1400})
    errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(url(d, "depart1")); pg.wait_for_timeout(300)
    st = pg.inner_text(".start").replace("\u00a0", " ")
    ok("T4 est vide." in st and pg.locator("[data-ld]").count() == 1, "« Au départ » : T4 vide signalée, un bouton « Charger »")
    lab = pg.inner_text("[data-ld]"); hv, av, sv = [int(x) for x in pg.get_attribute("[data-ld]", "data-ld").split("_")]
    ok(hv == 3 and sv == 3 and lab == "Charger T4 depuis ACE %d, voie 4" % (av + 1), "le bouton charge T4 depuis sa voie du plan (%s)" % lab)
    ok("T4 est vide : charge avant de lancer." in pg.inner_text(".bar").replace("\u00a0", " ") and not pg.is_disabled("#go"), "rappel près du lancement, rien n'est bloqué")
    pg.click("[data-ld]"); pg.wait_for_timeout(80)
    ok(pg.evaluate("window.__p")[-1] == {"a": "load", "head": 3, "ace": av, "slot": 3}, "clic : chargement demandé à la fenêtre")
    ok("✓ Chargement de T4 demandé" in pg.inner_text(".start") and "est vide :" not in pg.inner_text(".bar"), "chargement noté")
    d2 = json.loads(json.dumps(d)); d2["load"]["heads"][3]["loaded"] = True; d2["load"]["heads"][3].update(ace=av, slot=3)
    pg.goto(url(d2, "depart2")); pg.wait_for_timeout(300)
    ok(pg.locator(".ld").count() == 0, "toutes les têtes chargées : rien à faire")
    ok(not errs, "aucune erreur JavaScript %s" % errs)
    b.close()
mb._LANG["v"] = "en"
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome"); pg = b.new_page(viewport={"width": 1220, "height": 1400})
    pg.goto(url(d, "depart1_en", en=True)); pg.wait_for_timeout(300)
    t = pg.inner_text(".start") + pg.inner_text(".bar")
    ok("T4 is empty." in t and "Load T4 from ACE" in t and "error 523" in t and not any(w in t for w in ("vide", "Charger", "voie", "depuis")), "traduit")
    b.close()
mb._LANG["v"] = "fr"
calls, replies = [], []
run0, rep0 = mb._PANEL._run, W._reply
mb._PANEL._run = lambda n, a, allow_busy=False: calls.append((n, a))
W._reply = lambda ok_, text, final=False, step=None: replies.append(text)
try:
    for m in ({"a": "load", "head": 3, "ace": 1, "slot": 3}, {"a": "load", "head": "x"}, {"a": "load", "head": 9, "ace": 0, "slot": 0}):
        W.on_message(m)
finally:
    mb._PANEL._run, W._reply = run0, rep0
ok(calls == [("ACE_LOAD_HEAD", {"HEAD": 3, "ACE": 1, "SLOT": 3})] and "T4 (ACE 2, voie 4)" in replies[0], "Python : file du panneau, valeurs vérifiées")

# --- 2. éditeur : bobine #30 notée dans ACE 1 voie 1 (pas vide) choisie pour ACE 2 voie 1
state = {"aces": [{"idx": 0, "slots": [{"idx": 0, "state": "ready", "source": "rfid"}]},
                  {"idx": 1, "slots": [{"idx": 0, "state": "ready", "source": ""}]}],
         "spool_binding": {"0_0": 30}, "spools": {"30": {"id": 30}}}
ok(mb.spool_elsewhere(state, "30", 1, 0) == (0, 0) and mb.spool_elsewhere(state, "30", 0, 0) is None, "bobine notée dans une autre voie pas vide : repérée")
state_empty = json.loads(json.dumps(state)); state_empty["aces"][0]["slots"][0]["state"] = "empty"
ok(mb.spool_elsewhere(state_empty, "30", 1, 0) is None, "voie d'origine vide : rien à signaler")
class FakeClient:
    def __init__(self, host): self.calls = []; FakeClient.last = self
    def state(self, timeout=None): return state
    def set_override(self, *a): self.calls.append(("override",) + a)
    def macro(self, *a, **k): self.calls.append(("macro",) + a)
posted = []
P = mb._PANEL; MA, post0 = mb.MultiAce, P._post
mb.MultiAce = FakeClient; P._post = lambda msg: posted.append(msg)
try:
    P._edit({"ace": 1, "slot": 0, "color": "#ff0000", "material": "PLA", "spool": "30"})
    for _ in range(40):
        time.sleep(0.05)
        if posted: break
finally:
    mb.MultiAce, P._post = MA, post0
ok(posted and not posted[-1]["ok"] and "est dans ACE 1, voie 1" in posted[-1]["text"] and FakeClient.last.calls == [],
   "refusé en français avant d'écrire quoi que ce soit (%s)" % (posted[-1]["text"][:60] if posted else ""))

# --- 3. « Optimisé » impossible à cause des bobines chargées (T4 sans PLA identifié) : disposition de la U1
d3 = run([P_(0, 0, "#f4f4f4"), P_(0, 1, "#ffd23f"), P_(0, 2, "#2e9e4f")], [0, 1], "cas3.gcode")
o = d3["report"]["plans"]["optimize"]
ok(o.get("feasible") and o.get("suggested") and "head assignment" in str(o.get("live_reason")),
   "Optimisé : la U1 propose sa disposition (%s)" % o.get("live_reason"))
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome"); pg = b.new_page(viewport={"width": 1220, "height": 1400})
    pg.goto(url(d3, "depart3")); pg.wait_for_timeout(300)
    ok(pg.locator("#gopt").count() == 1, "l'avertissement propose le plan Optimisé")
    pg.click("#gopt"); pg.wait_for_timeout(150)
    steps = pg.inner_text("ul.st")
    ok(steps.count("pose une bobine") == 5 and pg.locator("#place").count() == 1, "5 bobines à poser, placement pas à pas")
    b.close()
mb._LANG["v"] = None
print("départ OK")
