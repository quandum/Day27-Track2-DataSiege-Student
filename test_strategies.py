#!/usr/bin/env python3
"""Test multiple defense strategies on public phase to find optimal score.
Creates temporary defense variants and tests each."""
import sys, json, shutil, os
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "harness"))
sys.path.insert(0, str(ROOT / "harness" / "child_env"))
import crypto
from isolation import IsolatedRun

BUDGET = 220.0

# Load schedule once
phases_dir = ROOT / "phases"
key = (phases_dir / "public.key").read_bytes()
ciphertext = (phases_dir / "public_schedule.json.enc").read_bytes()
schedule = crypto.decrypt_schedule(ciphertext, key)
events = schedule["events"]
truths = schedule["ground_truth"]
labels = schedule["labels"]
gt_by_key = {(t["type"], t["batch_id_or_ref"]): t["gt"] for t in truths}
baseline = json.loads((ROOT / "data" / "baselines.json").read_text())
baseline_path = str(ROOT / "data" / "baselines.json")

# Read current defense.py
defense_original = (ROOT / "solution" / "defense.py").read_text()

strategies = []

# Strategy 1: Relax thresholds by 10% (alert at 90% of baseline max)
s1 = defense_original
s1 = s1.replace("return True  # no throttle", "return remaining >= max(cost, 20.0)")
# Replace _exceeds to use 90% threshold
s1 = s1.replace(
    "def _exceeds(value, threshold):\n    \"\"\"Check if a numeric value exceeds a given upper-bound threshold.\"\"\"\n    if value is None or threshold is None:\n        return False\n    return value > threshold",
    "def _exceeds(value, threshold):\n    \"\"\"Check if a numeric value exceeds a given upper-bound threshold (with 10% margin).\"\"\"\n    if value is None or threshold is None:\n        return False\n    return value > threshold * 0.9"
)
s1 = s1.replace(
    "def _below(value, threshold):\n    \"\"\"Check if a numeric value falls below a given lower-bound threshold.\"\"\"\n    if value is None or threshold is None:\n        return False\n    return value < threshold",
    "def _below(value, threshold):\n    \"\"\"Check if a numeric value falls below a given lower-bound threshold (with 10% margin).\"\"\"\n    if value is None or threshold is None:\n        return False\n    return value < threshold * 1.1"
)
strategies.append(("relaxed_10pct", s1))

# Strategy 2: Tighten thresholds by 10% (alert at 110% of baseline max)
s2 = defense_original
s2 = s2.replace("return True  # no throttle", "return remaining >= max(cost, 20.0)")
s2 = s2.replace(
    "def _exceeds(value, threshold):\n    \"\"\"Check if a numeric value exceeds a given upper-bound threshold.\"\"\"\n    if value is None or threshold is None:\n        return False\n    return value > threshold",
    "def _exceeds(value, threshold):\n    \"\"\"Check if a numeric value exceeds a given upper-bound threshold (with 10% tightening).\"\"\"\n    if value is None or threshold is None:\n        return False\n    return value > threshold * 1.1"
)
s2 = s2.replace(
    "def _below(value, threshold):\n    \"\"\"Check if a numeric value falls below a given lower-bound threshold.\"\"\"\n    if value is None or threshold is None:\n        return False\n    return value < threshold",
    "def _below(value, threshold):\n    \"\"\"Check if a numeric value falls below a given lower-bound threshold (with 10% tightening).\"\"\"\n    if value is None or threshold is None:\n        return False\n    return value < threshold * 0.9"
)
strategies.append(("tightened_10pct", s2))

# Strategy 3: Current best (threshold=20 throttle, strict baseline) - just use original with throttle
s3 = defense_original.replace("return True  # no throttle", "return remaining >= max(cost, 20.0)")
strategies.append(("current_best", s3))

# Test each strategy
print(f"{'Strategy':<20} {'TPR':>8} {'FPR':>8} {'Cost':>8} {'Over':>8} {'Score':>8}")
print("-" * 65)

for name, code in strategies:
    # Write temp defense
    tmp_path = ROOT / "solution" / f"_tmp_defense_{name}.py"
    tmp_path.write_text(code)
    
    run = IsolatedRun(str(tmp_path), baseline_path, gt_by_key, budget=BUDGET)
    verdicts = []
    try:
        for ev in events:
            verdicts.append(run.dispatch(ev))
    finally:
        run.shutdown()
    
    # Score manually
    tp = fp = tn = fn = 0
    for v, label in zip(verdicts, labels):
        alerted = bool(v.get("alert"))
        actual = label["is_faulty"]
        if actual and alerted: tp += 1
        elif actual and not alerted: fn += 1
        elif not actual and alerted: fp += 1
        else: tn += 1
    
    cost = run.toolkit.cost_ledger
    tpr = tp / (tp + fn) if (tp + fn) else 0
    fpr = fp / (fp + tn) if (fp + tn) else 0
    overage = max(0, cost - BUDGET) / BUDGET if BUDGET else 0
    score = round(100 * (0.5 * tpr - 0.3 * fpr - 0.2 * min(overage, 1)), 2)
    
    print(f"{name:<20} {tpr:>8.4f} {fpr:>8.4f} {cost:>8.1f} {overage:>8.4f} {score:>8.2f}")
    
    # Cleanup
    tmp_path.unlink()

# Restore original
(ROOT / "solution" / "defense.py").write_text(defense_original)
print("\nRestored original defense.py")
