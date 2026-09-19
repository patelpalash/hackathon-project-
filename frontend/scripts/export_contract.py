"""Export the actual FastAPI wire contract for frontend type generation."""
import json
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root))
from backend.app.api.main import app

(root / 'frontend' / 'openapi.runtime.json').write_text(json.dumps(app.openapi(), indent=2), encoding='utf-8')
