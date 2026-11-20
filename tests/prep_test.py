"""Assistant « avant de trancher » + buses reelles (cas du dragon)."""
import json, os, sys, types, importlib.util, tempfile
STORE = tempfile.mkdtemp()
sys.modules["orca"] = types.SimpleNamespace(pages=types.SimpleNamespace(PagesPluginCapabilityBase=object),
  slicing=types.SimpleNamespace(SlicingPipelineCapabilityBase=object), script=types.SimpleNamespace(ScriptPluginCapabilityBase=object),
  base=object, plugin=lambda c: c, host=types.SimpleNamespace(plugin=types.SimpleNamespace(storage=lambda: STORE)))
spec = importlib.util.spec_from_file_location("mb", "/home/claude/multiace_bridge/multiace_bridge_any.py"); mb = importlib.util.module_from_spec(spec); spec.loader.exec_module(mb)
ok = lambda c, m: print(("PASS " if c else "FAIL ") + m) or (c or sys.exit(1))
HD, ST = "Haut débit", "Standard"
def slot(i, col):
    return {"idx": i, "state": "ready" if col else "empty", "color": col, "material": "PLA" if col else "", "source": "rfid" if col else "empty"}
def st(a1, a2):
    return {"aces": [{"idx": 0, "slots": [slot(i, c) for i, c in enumerate(a1)]}, {"idx": 1, "slots": [slot(i, c) for i, c in enumerate(a2)]}],
            "toolheads": [{"idx": i, "manual": False} for i in range(4)], "device_count": 2, "printer_state": "ready"}
BROWN, RED, BLACK, WHITE, GREEN, YEL = "#8D6E63", "#E53935", "#000000", "#FFFFFF", "#43A047", "#F7D959"
dragon = st([WHITE, BROWN, None, GREEN], [None, YEL, RED, BLACK])
real = [HD, HD, ST, HD]
orca_cols = ["#8E6F64FF", "#E43A36FF", "#000000FF", "#FFFFFFFF"]       # couleurs d'Orca (avec alpha, a peine differentes)

a = mb.slicing_advice(dragon, real, orca_cols, [HD, HD, ST, HD])
r = {x["t"]: x for x in a["rows"]}
ok((r[0]["ace"], r[0]["slot"], r[0]["need"], r[0]["ok"]) == (0, 1, HD, True), "marron -> ACE 1 slot 2 -> T2 Haut débit : bon")
ok((r[1]["head"], r[1]["need"], r[1]["ok"]) == (2, ST, False), "rouge -> T3 Standard : Orca T2 à changer")
ok((r[2]["head"], r[2]["need"], r[2]["ok"]) == (3, HD, False), "noir -> T4 Haut débit : Orca T3 à changer")
ok(r[3]["head"] == 0 and r[3]["ok"], "blanc -> T1 : bon")
ok(a["todo"] == [{"t": 1, "need": ST}, {"t": 2, "need": HD}], "à régler : T2 Standard, T3 Haut débit (l'astuce trouvée à la main) %s" % a["todo"])
a2 = mb.slicing_advice(dragon, real, orca_cols, [HD, ST, HD, HD])
ok(a2["todo"] == [] and all(x["ok"] for x in a2["rows"]), "une fois réglé dans Orca : tout est vert")
old = st([WHITE, None, BROWN, GREEN], [None, YEL, RED, BLACK])
a3 = mb.slicing_advice(old, real, orca_cols, [HD, HD, ST, HD])
ok(a3["shared"] == [{"head": 2, "filaments": [0, 1]}], "marron et rouge en slot 3 -> même tête T3 signalée")
a4 = mb.slicing_advice(dragon, real, orca_cols + ["#123456"], [HD, HD, ST, HD])
ok(a4["extra"] == 1, "5e filament signalé non vérifié")
a5 = mb.slicing_advice(dragon, real, ["#0000FF"], [HD])
ok(not a5["rows"][0]["found"] and a5["todo"] == [], "couleur absente des ACE -> signalée, rien à régler")
a6 = mb.slicing_advice(dragon, ["", "", "", ""], orca_cols, [HD, HD, ST, HD])
ok(not a6["real_known"] and a6["todo"] == [], "buses réelles pas renseignées -> pas de conseil")
two_reds = st([WHITE, BROWN, None, RED], [None, YEL, RED, BLACK])
a7 = mb.slicing_advice(two_reds, real, orca_cols, [HD, HD, ST, HD])
ok(a7["rows"][1]["ok"] is True and a7["rows"][1]["head"] == 3 and a7["todo"] == [{"t": 2, "need": HD}], "deux rouges identiques -> celui qui ne demande aucun changement (T4)")

# fenetre : tranche avec l'astuce + buses reelles -> plus de fausse alerte
g = open("five.gcode").read().replace("; filament_type = PLA;PLA;PLA;PLA;PLA", "; filament_type = PLA;PLA;PLA;PLA;PLA\n; filament used [g] = 50.0,70,10,10,10\n; nozzle_volume_type = Standard,Standard,High Flow,Standard\n; filament_map = 1,2,3,4,4")
bad = st(["#ffffff", "#000000", "#43a047", "#e53935"], [None, "#f7d959", None, None])
r1 = mb.analyze_gcode(g, bad)
ok(r1["nozzle_risk"] == [2, 4], "sans buses réelles : on croit Orca -> risque %s" % r1["nozzle_risk"])
r2 = mb.analyze_gcode(g, bad, real=[ST, ST, ST, HD])
ok(r2["nozzle_risk"] == [] and not any("buse" in x for x in r2["alerts"]), "avec les vraies buses : tranchage = réalité, aucune alerte")
r3 = mb.analyze_gcode(g, bad, real=[ST, ST, HD, ST])
ok(r3["nozzle_risk"] == [2, 4], "vraies buses identiques à Orca : même résultat qu'avant")
m = {x["t"]: x for x in r2["matches"]}
ok(m[2]["sliced_type"] == HD and m[2]["head_type"] == HD and m[4]["sliced_type"] == ST and m[4]["head_type"] == ST, "buse du tranchage et buse réelle distinguées")

# lecture d'OrcaSlicer (formats serialises d'Orca : chaines entre guillemets ; enums separes par des virgules)
class Pre:
    def __init__(s, m): s.m = m
    def config_value(s, k): return s.m if k == "printer_model" else None
class Bundle:
    def __init__(s, m): s.m = m
    def current_printer_preset(s): return Pre(s.m)
    def full_config_value(s, k):
        return {"filament_colour": '"#8E6F64FF";"#E43A36FF";"#000000FF";"#FFFFFFFF"',
                "nozzle_volume_type": "High Flow,Standard,High Flow,High Flow"}.get(k)
mb.orca.host.preset_bundle = lambda: Bundle("Snapmaker U1")
cols, noz = mb.orca_filament_setup()
ok(cols == ["#8E6F64FF", "#E43A36FF", "#000000FF", "#FFFFFFFF"] and noz == [HD, ST, HD, HD], "lecture Orca : %s %s" % (cols, noz))
ok(mb.slicing_advice(dragon, real, cols, noz)["todo"] == [], "le dragon tel que réglé par Dragg -> tout bon")
mb.orca.host.preset_bundle = lambda: Bundle("Bambu Lab P1S")
ok(mb.orca_filament_setup() is None, "autre imprimante -> pas de carte")
def boom(): raise RuntimeError("x")
mb.orca.host.preset_bundle = boom
ok(mb.orca_filament_setup() is None, "Orca qui ne répond pas -> pas de carte, pas d'erreur")

# panneau
fake = """<script>window.__h=[];window.__p=[];window.orca={postMessage:function(m){window.__p.push(typeof m==="string"?JSON.parse(m):m)},onMessage:function(f){window.__h.push(f)}};</script>"""
open("prep.html", "w").write(mb.PANEL.replace("__VERSION__", mb.VERSION).replace("<head>", "<head>" + fake, 1).replace("<body>", '<body style="background:#25282c">', 1))
state = json.load(open("/home/claude/src/multiACE/tests/fixtures/mock_state.json"))
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome")
    pg = b.new_page(viewport={"width": 320, "height": 1000}); pg.goto("file://" + os.path.abspath("prep.html")); pg.wait_for_timeout(200)
    send = lambda msg: pg.evaluate("m=>window.__h.forEach(f=>f(m))", msg)
    send({"command": "state", "state": state, "prep": dict(a6, real=["", "", "", ""])})
    ok("Indique une seule fois la buse vissée" in pg.inner_text("#prep"), "buses réelles inconnues -> invitation")
    pg.select_option('select[data-rn="2"]', ST)
    sent = [x for x in pg.evaluate("window.__p") if x.get("command") == "prefs_set"]
    ok(sent and sent[-1]["real_nozzles"] == ["", "", ST, ""], "choix envoyé au plugin : %s" % sent[-1])
    pg.wait_for_timeout(300)
    ok(any(x.get("command") == "refresh" for x in pg.evaluate("window.__p")), "puis actualisation")
    send({"command": "state", "state": state, "prep": dict(a, real=real)})
    t = pg.inner_text("#prep")
    cells = pg.locator("#prep .nc").all_inner_texts()
    ok("Mets ça à gauche" in t and cells == ["T1 Haut débit", "T2 STANDARD ←", "T3 HAUT DÉBIT ←", "T4 Haut débit"], "grille comme le bloc Buse d'Orca : %s" % cells)
    ok(pg.locator("#prep .nc.chg").count() == 2, "seules les 2 cases à changer en couleur")
    ok(not pg.is_visible("#prep select") and not pg.is_visible("text=Marron"), "détail et « Ma U1 » repliés")
    pg.click("text=Détail par filament")
    send({"command": "state", "state": state, "prep": dict(a, real=real)})
    ok(pg.is_visible("text=Filament 2"), "repli ouvert : reste ouvert à l'actualisation")
    pg.click("text=Détail par filament")
    pg.screenshot(path="v250_prep.png", clip={"x": 0, "y": 0, "width": 320, "height": 300})
    send({"command": "state", "state": state, "prep": dict(a3, real=real)})
    ok("même tête T3" in pg.inner_text("#prep"), "doublon de tête signalé")
    send({"command": "state", "state": state, "prep": dict(a2, real=real)})
    ok("buses d’OrcaSlicer OK" in pg.inner_text("#prep") and pg.locator("#prep .nc").count() == 0, "tout bon -> une ligne verte")
    pg.screenshot(path="v250_ok.png", clip={"x": 0, "y": 0, "width": 320, "height": 160})
    send({"command": "state", "state": state})
    ok(pg.inner_text("#prep").strip() == "", "pas une U1 / Orca illisible -> carte masquée")
    b.close()
print("ALL OK")
