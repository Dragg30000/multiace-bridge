import sys, types, importlib.util, tempfile, time, json
STORE = tempfile.mkdtemp()
cfg = {"v": ""}; sets = []
class Tx:
    def set(s, k, v): sets.append((k, v)); cfg["v"] = v
    def commit(s): pass
class P:
    def __init__(s, d): s.d = d
    def config_value(s, k): return s.d.get(k, "")
bundle = types.SimpleNamespace(current_printer_preset=lambda: P({"printer_model": "Snapmaker U1", "print_host": "192.168.1.50"}),
                               full_config_value=lambda k: "",
                               prints=types.SimpleNamespace(edited_preset=lambda: P({"slicing_pipeline_plugin": cfg["v"]})))
sys.modules["orca"] = types.SimpleNamespace(pages=types.SimpleNamespace(PagesPluginCapabilityBase=object),
  slicing=types.SimpleNamespace(SlicingPipelineCapabilityBase=object), script=types.SimpleNamespace(ScriptPluginCapabilityBase=object),
  base=object, plugin=lambda c: c, host=types.SimpleNamespace(plugin=types.SimpleNamespace(storage=lambda: STORE), preset_bundle=lambda: bundle,
  preset=types.SimpleNamespace(process=types.SimpleNamespace(begin_update=lambda preset_name="": Tx()))))
spec = importlib.util.spec_from_file_location("mb", "/home/claude/multiace_bridge/multiace_bridge_any.py"); mb = importlib.util.module_from_spec(spec); spec.loader.exec_module(mb)
ok = lambda c, m: print(("PASS " if c else "FAIL ") + m) or (c or sys.exit(1))
mb.ensure_pipeline_async(delay=0); time.sleep(0.3)
ok(sets == [("slicing_pipeline_plugin", '"multiACE : envoyer au Preflight"')], "pipeline added to empty process: %s" % sets)
mb.ensure_pipeline_async(delay=0); time.sleep(0.3); ok(len(sets) == 1, "not added twice")
cfg["v"] = '"Autre plugin"'; mb.ensure_pipeline_async(delay=0); time.sleep(0.3)
ok(sets[-1][1] == '"Autre plugin";"multiACE : envoyer au Preflight"', "existing plugins kept: " + sets[-1][1])
ok(mb.effective_host() == "192.168.1.50" and mb.load_settings()["host"] == "192.168.1.50", "preset host remembered for load-time permission")
reg = {}
mb.orca.request_permissions = lambda **k: reg.update(k); mb.orca.register_capability = lambda c: None
mb.MultiAceBridge().register_capabilities(); ok(reg["network"] == ["http://192.168.1.50"] and reg["threading"], "permissions requested at load: %s" % reg)
print("ALL OK")

# chargement sans stockage disponible : l'adresse est relue a cote de orca_plugins
import os, tempfile, json as _j
d = tempfile.mkdtemp(); os.makedirs(os.path.join(d, "orca_plugins", "p"), exist_ok=True); os.makedirs(os.path.join(d, "multiace_bridge"))
_j.dump({"host": "10.0.0.7"}, open(os.path.join(d, "multiace_bridge", "settings.json"), "w"))
mb.__file__ = os.path.join(d, "orca_plugins", "p", "multiace_bridge_any.py")
_ls = mb.load_settings; mb.load_settings = lambda: (_ for _ in ()).throw(RuntimeError("no storage"))
reg.clear(); mb.MultiAceBridge().register_capabilities(); mb.load_settings = _ls
assert reg.get("network") == ["http://10.0.0.7"], reg
print("LOAD-TIME PERMISSION OK")
