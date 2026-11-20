import sys, types, tempfile, importlib.util
S = tempfile.mkdtemp()
sys.modules["orca"] = types.SimpleNamespace(pages=types.SimpleNamespace(PagesPluginCapabilityBase=object), slicing=types.SimpleNamespace(SlicingPipelineCapabilityBase=object), script=types.SimpleNamespace(ScriptPluginCapabilityBase=object), base=object, plugin=lambda c: c, host=types.SimpleNamespace(plugin=types.SimpleNamespace(storage=lambda: S)))
sp = importlib.util.spec_from_file_location("mb", "/home/claude/multiace_bridge/multiace_bridge_any.py"); mb = importlib.util.module_from_spec(sp); sp.loader.exec_module(mb)
g = mb.gcode_safe
assert g('SUNLU"\nG28; M112 #x*') == "SUNLU G28 M112 x", repr(g('SUNLU"\nG28; M112 #x*'))
assert "\n" not in g("a\r\nb") and "\x00" not in g("a\x00b") and len(g("x" * 500)) == 40
for bad in ["http://evil/../x", "1.2.3.4/path?x", "a b", "u1.local\r\nHost: x", ""]:
    h = mb.normalize_host(bad); assert "/" not in h and " " not in h and "\n" not in h, (bad, h)
c = mb.AcePanelController(); sent = []; c._post = sent.append
c._edit({"ace": 0, "slot": 0, "color": "#ff0000", "weight": "inf"})          # pas d'exception
c._edit({"ace": 99, "slot": 0, "color": "#ff0000"}); c._edit({"ace": 0, "slot": 0, "color": "red;G28"})
assert any("Couleur invalide" in (p.get("text") or "") for p in sent)
c.on_message({"command": "calib_bed", "temp": "1e9"}); c.on_message({"command": "calib_pa", "head": 9, "ace": 0, "slot": 0})
assert not c._queue, c._queue
print("SECURITY OK")

# l'en-tete lu par OrcaSlicer (liste des plugins) doit porter la meme version que le panneau
import re as _re
_src = open("/home/claude/multiace_bridge/multiace_bridge_any.py", encoding="utf-8").read()
_h = _re.search(r'^# version = "([^"]+)"', _src, _re.M).group(1)
_v = _re.search(r'^VERSION = "([^"]+)"', _src, _re.M).group(1)
assert _h == _v, "en-tete %s != VERSION %s" % (_h, _v)
print("VERSION OK", _v)
