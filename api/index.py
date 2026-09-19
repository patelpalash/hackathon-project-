import os
import sys
from pathlib import Path

# Ensure backend directory is on sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Ensure DATA_DIR is configured
if "DATA_DIR" not in os.environ:
    os.environ["DATA_DIR"] = str(ROOT_DIR / "data" / "raw")

from app.main import app
