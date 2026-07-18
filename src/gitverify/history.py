import json
from pathlib import Path

HISTORY_PATH = Path.home() / ".config" / "gitverify" / "history.json"


def _load() -> dict:
    if not HISTORY_PATH.exists():
        return {}
    return json.loads(HISTORY_PATH.read_text())


def get_previous(handle: str) -> dict | None:
    return _load().get(handle)


def save_result(handle: str, score: float, band: str, axes: dict[str, float]) -> None:
    history = _load()
    history[handle] = {"score": score, "band": band, "axes": axes}
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_PATH.write_text(json.dumps(history, indent=2))
