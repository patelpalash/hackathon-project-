import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

if "DATA_DIR" not in os.environ:
    os.environ["DATA_DIR"] = str(ROOT_DIR / "data" / "raw")

from backend.app.main import app

__all__ = ["app"]
