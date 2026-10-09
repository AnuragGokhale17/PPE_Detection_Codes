import sys
from pathlib import Path

# The worker modules live at the repository root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
