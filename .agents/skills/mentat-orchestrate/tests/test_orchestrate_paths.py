import importlib.util
import sys
from pathlib import Path

ROOT = Path.home() / ".agents" / "skills" / "mentat-orchestrate" / "scripts"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _no_double(p: Path) -> None:
    assert ".agents/.agents" not in str(p), f"double .agents/ prefix in {p}"


def test_utils_paths():
    u = _load("utils")
    _no_double(u._LOG_SCRIPT)
    assert u._LOG_SCRIPT.is_file(), u._LOG_SCRIPT
    _no_double(u._GATES_CODE)


def test_fan_out_paths():
    f = _load("fan_out")
    _no_double(f._LOG_SCRIPT)
    assert f._LOG_SCRIPT.is_file(), f._LOG_SCRIPT
    _no_double(f._IMPLEMENT_SCRIPT)
    assert f._IMPLEMENT_SCRIPT.is_file(), f._IMPLEMENT_SCRIPT
    _no_double(f._CONTAINER_SCRIPT)
    assert f._CONTAINER_SCRIPT.is_file(), f._CONTAINER_SCRIPT


def test_orchestrate_no_double_prefix():
    src = (ROOT / "orchestrate.py").read_text()
    assert '".agents/skills/mentat-implement' not in src, (
        "orchestrate.py still has double .agents/ prefix in implement_script join"
    )
