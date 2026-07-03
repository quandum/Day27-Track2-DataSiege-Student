#!/usr/bin/env python3
"""Debug: re-run defense.py against answer key and show per-event comparison.
Usage: python3 debug_compare.py"""
import sys
import json
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "harness"))          # crypto, scoring, signing, isolation, toolkit
sys.path.insert(0, str(ROOT / "harness" / "child_env"))  # api, child_driver

import crypto
from isolation import IsolatedRun

BUDGET = 220.0


def main():
    # Load answer key
    answer_key = json.loads((ROOT / "phases" / "practice_answer_key.json").read_text())
    baseline = json.loads((ROOT / "data" / "baselines.json").read_text())

    # Decrypt schedule
    phases_dir = ROOT / "phases"
    key = (phases_dir / "practice.key").read_bytes()
    ciphertext = (phases_dir / "practice_schedule.json.enc").read_bytes()
    schedule = crypto.decrypt_schedule(ciphertext, key)

    events = schedule["events"]
    truths = schedule["ground_truth"]
    gt_by_key = {(t["type"], t["batch_id_or_ref"]): t["gt"] for t in truths}

    defense_path = str(ROOT / "solution" / "defense.py")
    baseline_path = str(ROOT / "data" / "baselines.json")

    run = IsolatedRun(defense_path, baseline_path, gt_by_key, budget=BUDGET)

    results = []
    try:
        for i, ev in enumerate(events):
            verdict = run.dispatch(ev)
            actual = answer_key[i]
            results.append({
                "seq": i,
                "event_type": ev["type"],
                "payload_ref": ev["payload"].get("batch_id") or ev["payload"].get("checkpoint_batch_id")
                               or ev["payload"].get("run_id") or ev["payload"].get("chunk_batch_id") or "?",
                "verdict_alert": bool(verdict.get("alert")),
                "verdict_reason": verdict.get("reason", "")[:100],
                "actual_faulty": actual["is_faulty"],
                "fault_key": actual["fault_key"],
                "pillar": actual["pillar"],
                "tier": actual["tier"],
            })
    finally:
        run.shutdown()

    cost = run.toolkit.cost_ledger

    # Show results
    print(f"{'Seq':>4} {'Type':<25} {'Ref':<12} {'Alert':>5} {'Truth':>5} {'Match':>5} {'Pillar':<12} {'Key':<22} {'Tier':<8} Reason")
    print("-" * 140)

    tp = fp = tn = fn = 0
    missed = []

    for r in results:
        match = "✓" if r["verdict_alert"] == r["actual_faulty"] else "✗"
        if r["actual_faulty"] and r["verdict_alert"]:
            tp += 1
        elif r["actual_faulty"] and not r["verdict_alert"]:
            fn += 1
            missed.append(r)
        elif not r["actual_faulty"] and r["verdict_alert"]:
            fp += 1
        else:
            tn += 1

        # Only show faulty events and mismatches
        if r["actual_faulty"] or r["verdict_alert"]:
            print(f"{r['seq']:>4} {r['event_type']:<25} {str(r['payload_ref']):<12} "
                  f"{str(r['verdict_alert']):>5} {str(r['actual_faulty']):>5} {match:>5} "
                  f"{str(r['pillar'] or 'n/a'):<12} {str(r['fault_key'] or '-'):<22} "
                  f"{str(r['tier'] or '-'):<8} {r['verdict_reason'][:60]}")

    print("-" * 140)
    print(f"\nTP={tp}  FP={fp}  TN={tn}  FN={fn}")
    tpr = tp / (tp + fn) if (tp + fn) else 0
    fpr = fp / (fp + tn) if (fp + tn) else 0
    raw = 0.5 * tpr - 0.3 * fpr - 0.2 * min(max(0, cost - BUDGET) / BUDGET, 1)
    print(f"TPR={tpr:.4f}  FPR={fpr:.4f}  Cost={cost:.1f}/{BUDGET}  Score={raw*100:.2f}")

    if missed:
        print(f"\n⚠ MISSED FAULTS ({len(missed)}):")
        for m in missed:
            print(f"  seq={m['seq']}  type={m['event_type']}  pillar={m['pillar']}  "
                  f"key={m['fault_key']}  tier={m['tier']}")


if __name__ == "__main__":
    main()
