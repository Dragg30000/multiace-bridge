"""0.43.1 : plusieurs bobines pareilles. Une bobine de la table multiACE posée dans une autre voie occupée, choisie
pour une voie : nouvelle bobine pareille liée à cette voie (ACE_SPOOL_ADD + ACE_SPOOL_PA), l'originale ne bouge pas."""
import json, sys, time, types, importlib.util, tempfile
STORE = tempfile.mkdtemp()
sys.modules["orca"] = types.SimpleNamespace(pages=types.SimpleNamespace(PagesPluginCapabilityBase=object),
  slicing=types.SimpleNamespace(SlicingPipelineCapabilityBase=object), script=types.SimpleNamespace(ScriptPluginCapabilityBase=object),
  base=object, plugin=lambda c: c, host=types.SimpleNamespace(plugin=types.SimpleNamespace(storage=lambda: STORE)))
spec = importlib.util.spec_from_file_location("mb", "/home/claude/prive/multiace_bridge_any.py"); mb = importlib.util.module_from_spec(spec); spec.loader.exec_module(mb)
FAILS = []
def ok(c, m):
    print(("PASS " if c else "FAIL ") + m)
    if not c: FAILS.append(m)

def base_state():
    return {"aces": [{"idx": 0, "slots": [{"idx": 2, "state": "ready", "source": "override"}]},
                     {"idx": 1, "slots": [{"idx": 2, "state": "ready", "source": "rfid"}]}],
            "spool_binding": {"1_2": 30},
            "spools": {"30": {"id": 30, "label": "Rouge SUNLU", "vendor": "SUNLU", "material": "PLA", "color": "E53935",
                              "density": 1.24, "weight_g": 410, "weight_initial_g": 1000,
                              "pa_matrix": {"0.4_standard": 0.035, "0.4_high_flow": 0.028, "bad key": 9}}}}

class FakeClient:
    pa_refused = False
    def __init__(self, host):
        self.calls = []; self.st = base_state(); FakeClient.last = self
    def state(self, timeout=None):
        return json.loads(json.dumps(self.st))
    def set_override(self, *a):
        self.calls.append(("override",) + a)
    def macro(self, name, args, timeout=None):
        self.calls.append(("macro", name, dict(args)))
        if name == "ACE_SPOOL_ADD":
            self.st["spools"]["31"] = {"id": 31}
            self.st["spool_binding"]["%d_%d" % (args["ACE"], args["SLOT"])] = 31
        if name == "ACE_SPOOL_PA" and FakeClient.pa_refused:
            raise mb.MultiAceError("PA is managed by SpoolLink in this spool mode")

posted = []
P = mb._PANEL; MA, post0 = mb.MultiAce, P._post
def edit(m):
    posted.clear()
    mb.MultiAce = FakeClient; P._post = lambda msg: posted.append(msg)
    try:
        P._edit(m)
        for _ in range(60):
            time.sleep(0.05)
            if posted: break
    finally:
        mb.MultiAce, P._post = MA, post0
    return posted[-1] if posted else None

# 1. deuxième rouge en ACE 1, voie 3 : la bobine #30 (ACE 2, voie 3, pas vide) choisie
r = edit({"ace": 0, "slot": 2, "color": "#e53935", "material": "PLA", "brand": "SUNLU", "subtype": "", "weight": "1000", "spool": "copy:30"})
ok(r and r["ok"] and "Nouvelle bobine pareille au #30 dans l'ACE 1, voie 3" in r["text"], "copie acceptée : %s" % (r or {}).get("text"))
calls = FakeClient.last.calls
add = [c for c in calls if c[0] == "macro" and c[1] == "ACE_SPOOL_ADD"]
ok(calls[0] == ("override", 0, 2, "PLA", "SUNLU", "", "#e53935"), "la voie prend la couleur et la matière")
ok(add and add[0][2] == {"MATERIAL": "PLA", "COLOR": "E53935", "ACE": 0, "SLOT": 2, "VENDOR": "SUNLU", "LABEL": "Rouge SUNLU",
                         "DENSITY": 1.24, "WEIGHT": 1000}, "nouvelle bobine pareille (marque, matière, couleur, nom, densité), liée à la voie : %s" % (add[0][2] if add else None))
pa = [c[2] for c in calls if c[0] == "macro" and c[1] == "ACE_SPOOL_PA"]
ok(pa == [{"ID": "31", "KEY": "0.4_high_flow", "VALUE": 0.028}, {"ID": "31", "KEY": "0.4_standard", "VALUE": 0.035}],
   "PA mémorisé repris sur la nouvelle bobine, clé invalide ignorée : %s" % pa)
ok(not any(c[0] == "macro" and c[1] in ("ACE_SPOOL_ASSIGN", "ACE_SPOOL_SET") for c in calls), "la bobine #30 n'est ni déplacée ni modifiée")
ok(calls[-1] == ("macro", "MULTIACE_REFRESH_OVERRIDES", {}), "multiACE relit les voies")
# 2. PA géré par SpoolLink : la copie se fait quand même
FakeClient.pa_refused = True
r = edit({"ace": 0, "slot": 2, "color": "#e53935", "material": "PLA", "spool": "copy:30"})
FakeClient.pa_refused = False
ok(r and r["ok"] and sum(1 for c in FakeClient.last.calls if c[1:2] == ("ACE_SPOOL_PA",)) == 1, "PA refusé (SpoolLink) : copie faite, PA non repris")
# 3. refus
r = edit({"ace": 0, "slot": 2, "color": "#e53935", "material": "PLA", "spool": "copy:abc"})
ok(r and not r["ok"] and r["text"] == "Bobine invalide.", "copie illisible refusée")
r = edit({"ace": 0, "slot": 2, "color": "#e53935", "material": "PLA", "spool": "copy:99"})
ok(r and not r["ok"] and "introuvable" in r["text"] and not any(c[0] == "macro" for c in FakeClient.last.calls), "bobine inconnue : rien n'est écrit")
# 4. choix direct d'une bobine posée ailleurs (liste ancienne) : toujours refusé, avec la marche à suivre
r = edit({"ace": 0, "slot": 2, "color": "#e53935", "material": "PLA", "spool": "30"})
ok(r and not r["ok"] and "choisis-la de nouveau dans la liste" in r["text"] and FakeClient.last.calls == [], "choix direct : refusé, la copie est proposée")
# 5. anglais
mb._LANG["v"] = "en"
t = mb.tr("Nouvelle bobine pareille au #30 dans l'ACE 1, voie 3.")
mb._LANG["v"] = None
ok(t.startswith("New spool matching #30 in ACE 1, lane 3"), "anglais : %s" % t)
print("échecs :", len(FAILS))
sys.exit(1 if FAILS else 0)
