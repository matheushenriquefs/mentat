import sys
from pathlib import Path

ROOT = Path(__file__).parent
for skill_scripts in (ROOT / ".agents/skills").glob("mentat-*/scripts"):
    sys.path.insert(0, str(skill_scripts))
sys.path.insert(0, str(ROOT / ".agents/lib"))
sys.path.insert(0, str(ROOT / ".agents"))
