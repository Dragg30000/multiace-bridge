import os, sys, types, importlib.util, tempfile, json
DATA = tempfile.mkdtemp(); STORE = os.path.join(DATA, "orca_plugins", "storage", "multiace"); os.makedirs(STORE)
b = os.path.join(DATA, "user", "123", "_local", "multiace-bridge", "machine"); os.makedirs(b)
open(os.path.join(b, "Snapmaker U1 multiACE.json"), "w").write("{}"); open(os.path.join(DATA, "user", "123", "_local", "multiace-bridge", "bundle_metadata.json"), "w").write("{}")
keep = os.path.join(DATA, "user", "123", "machine"); os.makedirs(keep); open(os.path.join(keep, "Ma U1.json"), "w").write("{}")
cur = {"n": "Snapmaker U1 multiACE"}; reloads = []
bundle = types.SimpleNamespace(current_printer_preset=lambda: types.SimpleNamespace(name=cur["n"]))
sys.modules["orca"] = types.SimpleNamespace(pages=types.SimpleNamespace(PagesPluginCapabilityBase=object),
  slicing=types.SimpleNamespace(SlicingPipelineCapabilityBase=object), script=types.SimpleNamespace(ScriptPluginCapabilityBase=object),
  base=object, plugin=lambda c: c, host=types.SimpleNamespace(plugin=types.SimpleNamespace(storage=lambda: STORE), preset_bundle=lambda: bundle,
  preset=types.SimpleNamespace(bundles=types.SimpleNamespace(reload_local=lambda i: reloads.append(i)))))
spec = importlib.util.spec_from_file_location("mb", "/home/claude/multiace_bridge/multiace_bridge_any.py"); mb = importlib.util.module_from_spec(spec); spec.loader.exec_module(mb)
ok = lambda c, m: print(("PASS " if c else "FAIL ") + m) or (c or sys.exit(1))
ok(mb.remove_old_profile() is False and os.path.isdir(b), "not removed while it is the selected printer")
cur["n"] = "Snapmaker U1 (0.4 nozzle)"
ok(mb.remove_old_profile() is True and not os.path.exists(os.path.join(DATA, "user", "123", "_local", "multiace-bridge")) and reloads == ["multiace-bridge"], "old profile bundle removed + reloaded")
ok(os.path.exists(os.path.join(keep, "Ma U1.json")), "user's own presets untouched")
ok(mb.remove_old_profile() is False, "nothing to do the second time")
print("ALL OK")
