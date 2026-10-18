import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "finance_agent"

if __name__ == "__main__":
    script = ROOT / "eval" / "generate_evidence_doc.py"
    sys.exit(subprocess.call([sys.executable, str(script)] + sys.argv[1:], cwd=str(ROOT)))
