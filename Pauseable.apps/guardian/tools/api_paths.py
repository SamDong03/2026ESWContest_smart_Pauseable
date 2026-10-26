
from pathlib import Path
import sys

API_ROOT = Path(__file__).resolve().parents[2] / 'api'


def add_api_to_path() -> None:
    if not (API_ROOT / 'app' / '__init__.py').is_file():
        raise ModuleNotFoundError('Keep Pauseable.apps/api next to Pauseable.apps/guardian')
    location = str(API_ROOT)
    if location not in sys.path:
        sys.path.insert(0, location)
