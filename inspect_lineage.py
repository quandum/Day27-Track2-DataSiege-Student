#!/usr/bin/env python3
"""Inspect upstream/downstream values for ALL lineage events."""
import sys, json
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "harness"))
sys.path.insert(0, str(ROOT / "harness" / "child_env"))
import crypto
from isolation import IsolatedRun

answer_key = json.loads((ROOT / "phases" / "practice_answer_key.json").read_text())
baseline = json.loads((ROOT / "data" / "baselines.json").read_text())
phases_dir = ROOT / "phases"
key = (phases_dir / "practice.key").read_bytes()
ciphertext = (phases_dir / "practice_schedule.json.enc").read_bytes()
schedule = crypto.decrypt_schedule(ciphertext, key)
events = schedule["events"]
truths = schedule["ground_truth"]
gt_by_key = {(t["type"], t["batch_id_or_ref"]): t["gt"] for t in truths}

defense_path = str(ROOT / "solution" / "defense.py")
baseline_path = str(ROOT / "data" / "baselines.json")
run = IsolatedRun(defense_path, baseline_path, gt_by_key, budget=220.0)

print(f"{'Seq':>4} {'Type':<25} {'Ref':<10} {'Fault?':>6} {'Key':<22} {'dur_ms':>8} {'upstream':>20} {'down_cnt':>8}")
print("-" * 120)

try:
    for i, ev in enumerate(events):
        if ev["type"] != "lineage_run":
            continue
        ref = ev["payload"].get("run_id", "?")
        run.toolkit.reveal("lineage_run", ref)
        g = run.toolkit.lineage_graph_slice(ref)
        actual = answer_key[i]
        print(f"{i:>4} {ev['type']:<25} {str(ref):<10} {str(actual['is_faulty']):>6} {str(actual['fault_key'] or '-'):<22} "
              f"{g.get('duration_ms','?'):>8} {str(g.get('actual_upstream','?')):>20} {g.get('actual_downstream_count','?'):>8}")
finally:
    run.shutdown()
