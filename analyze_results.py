#!/usr/bin/env python3
"""Compare practice report verdicts against answer key to find missed faults."""
import json
from pathlib import Path

ROOT = Path(__file__).parent

# Load answer key
answer_key = json.loads((ROOT / "phases" / "practice_answer_key.json").read_text())
# Load practice report
report = json.loads((ROOT / "solution" / "practice_report.json").read_text())

# The report doesn't contain per-event verdicts — we need to re-run with debug.
# But we can read the schedule's ground_truth to compare.
# Actually, let's just look at the report's per_pillar_band and deduce.

print("=" * 60)
print("PRACTICE REPORT SUMMARY")
print("=" * 60)
result = report["result"]
print(f"Score: {result['score']}")
print(f"TPR: {result['tpr']}  |  FPR: {result['fpr']}")
print(f"Cost: {result['cost_ledger']} / {result['budget']}  |  Overage: {result['cost_overage']}")
print(f"Faults: {result['n_faulty']}  |  Clean: {result['n_clean']}")

print("\nPer-Pillar Bands:")
for p, band in sorted(result["per_pillar_band"].items()):
    print(f"  {p:20s} → {band}")

# Count faults per pillar from answer key
print("\n" + "=" * 60)
print("FAULT DISTRIBUTION (from answer key)")
print("=" * 60)
from collections import Counter
fault_counts = Counter()
tier_counts = Counter()
for entry in answer_key:
    if entry["is_faulty"]:
        p = entry["pillar"] or "n/a"
        fault_counts[p] += 1
        t = entry["tier"] or "n/a"
        tier_counts[(p, t)] += 1

for pillar in ["checks", "contracts", "lineage", "ai_infra"]:
    total = fault_counts.get(pillar, 0)
    obvious = tier_counts.get((pillar, "obvious"), 0)
    subtle = tier_counts.get((pillar, "subtle"), 0)
    na = tier_counts.get((pillar, "n/a"), 0)
    parts = []
    if obvious: parts.append(f"{obvious} obvious")
    if subtle: parts.append(f"{subtle} subtle")
    if na: parts.append(f"{na} n/a")
    print(f"  {pillar:20s}: {total} faults ({', '.join(parts)})")

# Estimate caught/missed per pillar
print("\n" + "=" * 60)
print("ESTIMATED CAUGHT/MISSED (from TPR per band)")
print("=" * 60)
# TPR overall = 0.8182 → 27/33 caught, 6 missed
band_to_tpr = {"high": 0.85, "medium": 0.6, "low": 0.3, "n/a": 0.0}
for pillar in ["checks", "contracts", "lineage", "ai_infra"]:
    band = result["per_pillar_band"].get(pillar, "n/a")
    total = fault_counts.get(pillar, 0)
    est_tpr = band_to_tpr.get(band, 0)
    caught = int(total * est_tpr)
    missed = total - caught
    print(f"  {pillar:20s}: band={band:6s} → ~{caught}/{total} caught, ~{missed} missed")

print("\nDone. Run with --debug flag or use the harness to get per-verdict details.")
