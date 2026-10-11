"""Evaluate the configured model on a labelled folder: data/real/*.jpg and data/fake/*.jpg.
Usage: python scripts/evaluate.py data/   (run from backend/, with SATYAM_HF_MODEL set)
Reports counts, class imbalance, FP/FN, and per-format breakdown. It reports only what the model returned;
files the model could not score are counted as 'no result', never guessed."""
import sys, collections, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from PIL import Image
from app.models.model_registry import get_detector

root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "data")
det = get_detector()
if not det.status()["ready"]:
    sys.exit(f"Model unavailable: {det.status()['reason']}")
cm, by_fmt, none = collections.Counter(), collections.defaultdict(collections.Counter), 0
for label in ("real", "fake"):
    for f in sorted((root / label).glob("*")):
        try:
            p = det.predict(Image.open(f)); got = "fake" if p["flagged"] else "real"
        except Exception:
            none += 1; continue
        cm[(label, got)] += 1; by_fmt[f.suffix.lower()][(label, got)] += 1
n_real, n_fake = sum(v for (l, _), v in cm.items() if l == "real"), sum(v for (l, _), v in cm.items() if l == "fake")
print(f"Model: {det.name}  scored: {n_real + n_fake}  no result: {none}")
print(f"Class balance: real={n_real} fake={n_fake}  (imbalance affects accuracy; read FP/FN, not accuracy alone)")
print(f"True real: {cm[('real','real')]}  False positives (real flagged fake): {cm[('real','fake')]}")
print(f"True fake: {cm[('fake','fake')]}  False negatives (fake missed): {cm[('fake','real')]}")
for ext, c in by_fmt.items(): print(f"  {ext}: FP={c[('real','fake')]} FN={c[('fake','real')]} n={sum(c.values())}")
print("Caveat: small or unrepresentative sets cannot establish reliability. Do not quote these numbers as accuracy.")
