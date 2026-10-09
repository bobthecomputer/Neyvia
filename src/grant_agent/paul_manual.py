"""Public distribution: no bundled personal profile or learned messages."""
from pathlib import Path
MANUAL = Path(__file__).resolve().parents[2] / "config/user_profile.json"
BRIEF_MIN_P = 0.7
def laplace(n: int, c: int) -> float:
    return (n + 1) / (n + c + 2)
def profile(path=MANUAL) -> dict:
    return {"rules": [], "judgements": []}
def validate(path=MANUAL) -> list[str]:
    return []
def brief(level=2, min_p=BRIEF_MIN_P, path=MANUAL) -> str:
    return ""
