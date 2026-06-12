import ast
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _src(name: str) -> str:
    return (_SCRIPTS / f"{name}.py").read_text()


def _no_double(p: Path) -> None:
    assert ".agents/.agents" not in str(p), f"double .agents/ prefix in {p}"


def test_utils_uses_paths_lib():
    """utils.py must import from lib.paths, not define its own _LOG_SCRIPT/_GATES_CODE."""
    src = _src("utils")
    tree = ast.parse(src)
    # `from lib import paths` → ImportFrom(module='lib', names=[alias(name='paths')])
    imports_paths = any(
        isinstance(node, ast.ImportFrom) and node.module == "lib" and any(alias.name == "paths" for alias in node.names)
        for node in ast.walk(tree)
    )
    assert imports_paths, "utils.py must do 'from lib import paths'"
    assert "_LOG_SCRIPT" not in src, "utils.py must not define _LOG_SCRIPT (use paths.LOG_SCRIPT)"
    assert "_GATES_CODE" not in src, "utils.py must not define _GATES_CODE (use paths.GATES_CODE_DIR)"


def test_fan_out_paths():
    import importlib.util

    import pytest

    root = Path.home() / ".agents" / "skills" / "mentat-orchestrate" / "scripts"
    fan_out_path = root / "fan_out.py"
    if not fan_out_path.exists():
        pytest.skip("~/.agents/ not present in this env")
    spec = importlib.util.spec_from_file_location("fan_out", fan_out_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["fan_out"] = mod
    spec.loader.exec_module(mod)
    _no_double(mod._LOG_SCRIPT)
    assert mod._LOG_SCRIPT.is_file(), mod._LOG_SCRIPT
    _no_double(mod._IMPLEMENT_SCRIPT)
    assert mod._IMPLEMENT_SCRIPT.is_file(), mod._IMPLEMENT_SCRIPT
    _no_double(mod._CONTAINER_SCRIPT)
    assert mod._CONTAINER_SCRIPT.is_file(), mod._CONTAINER_SCRIPT


def test_orchestrate_no_double_prefix():
    src = _src("orchestrate")
    assert '".agents/skills/mentat-implement' not in src, (
        "orchestrate.py still has double .agents/ prefix in implement_script join"
    )
