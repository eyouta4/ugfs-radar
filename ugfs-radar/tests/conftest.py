"""tests/conftest.py — Fixtures et config pytest globales."""
import sys
from pathlib import Path

# Permet d'importer `src.*` sans installer le package
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
