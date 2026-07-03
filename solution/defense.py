"""
Data Siege — Defense Module
Học viên: Trần Mạnh Chánh Quân — MSSV: 2A202600786

Detection strategy:
  - Primary: compare tool-call results against ctx.baseline thresholds (mean ± 3σ).
  - Secondary: combine multiple signals for subtle faults; track history in ctx.state.
  - Budget-aware: skip or downgrade expensive calls when budget is tight.
  - All thresholds derived from ctx.baseline — no hardcoded magic numbers.
"""
from collections import Counter
from api import Verdict

# ── helpers ──────────────────────────────────────────────────────────

def _is_error(result):
    """True if the tool returned an error sentinel (unknown / not-yet-visible id)."""
    return isinstance(result, dict) and "error" in result


def _exceeds(value, threshold):
    """Check if a numeric value exceeds a given upper-bound threshold."""
    if value is None or threshold is None:
        return False
    return value > threshold


def _below(value, threshold):
    """Check if a numeric value falls below a given lower-bound threshold."""
    if value is None or threshold is None:
        return False
    return value < threshold


def _outside(value, lo, hi):
    """Check if a numeric value falls outside [lo, hi]."""
    if value is None or lo is None or hi is None:
        return False
    return value < lo or value > hi


# ── budget helpers ────────────────────────────────────────────────────

def _budget_safe(ctx, cost=1.0):
    """Return True if we can afford this call. Always allow cheap tools;
    throttle expensive ones when budget is critically low."""
    remaining = ctx.tools.budget_remaining()
    if _is_error(remaining):
        return True
    # Always allow calls ≤ 1.5 credits; throttle 2.0-credit calls below 30 remaining
    if cost <= 1.5:
        return remaining >= cost
    return remaining >= max(cost, 30.0)


# ── registration ─────────────────────────────────────────────────────

def register(ctx):
    ctx.on("data_batch", check_data_batch)
    ctx.on("contract_checkpoint", check_contract_checkpoint)
    ctx.on("lineage_run", check_lineage_run)
    ctx.on("feature_materialization", check_feature_materialization)
    ctx.on("embedding_batch", check_embedding_batch)


# ══════════════════════════════════════════════════════════════════════
# Handler: data_batch  (pillar: checks)
# ══════════════════════════════════════════════════════════════════════

def check_data_batch(payload, ctx):
    """
    Check a data batch for volume, null-rate, mean-amount, and staleness faults.
    Combines multiple signals: a single borderline metric won't trigger, but
    a clear breach or multiple borderline metrics will.
    """
    batch_id = payload.get("batch_id", "?")
    b = ctx.baseline

    profile = ctx.tools.batch_profile(batch_id)
    if _is_error(profile):
        return Verdict(alert=False, pillar="checks",
                       reason=f"batch_profile failed: {profile.get('error')}")

    signals = []
    reasons = []

    # 1. row_count — must be within [min, max]
    rc = profile.get("row_count")
    if _below(rc, b.get("row_count_min")):
        signals.append(1.0)
        reasons.append(f"row_count {rc} < min {b['row_count_min']:.1f}")
    elif _exceeds(rc, b.get("row_count_max")):
        signals.append(1.0)
        reasons.append(f"row_count {rc} > max {b['row_count_max']:.1f}")

    # 2. null_rate on customer_id
    nr = profile.get("null_rate", {})
    nrc = nr.get("customer_id") if isinstance(nr, dict) else None
    if _exceeds(nrc, b.get("null_rate_max")):
        signals.append(1.0)
        reasons.append(f"null_rate(customer_id) {nrc:.4f} > max {b['null_rate_max']:.4f}")

    # 3. mean_amount — must be within [min, max]
    ma = profile.get("mean_amount")
    if _below(ma, b.get("mean_amount_min")):
        signals.append(0.8)
        reasons.append(f"mean_amount {ma:.2f} < min {b['mean_amount_min']:.2f}")
    elif _exceeds(ma, b.get("mean_amount_max")):
        signals.append(0.8)
        reasons.append(f"mean_amount {ma:.2f} > max {b['mean_amount_max']:.2f}")

    # 4. staleness_min
    sm = profile.get("staleness_min")
    if _exceeds(sm, b.get("staleness_min_max")):
        signals.append(0.9)
        reasons.append(f"staleness_min {sm:.2f} > max {b['staleness_min_max']:.2f}")

    # Decision: alert if any signal fires — baseline thresholds are mean ± 3σ,
    # so even a single breach is statistically significant.
    if not signals:
        return Verdict(alert=False, pillar="checks", reason="all metrics within baseline")
    confidence = min(1.0, 0.7 + 0.1 * len(signals))
    return Verdict(alert=True, pillar="checks", confidence=confidence,
                   reason="; ".join(reasons))


# ══════════════════════════════════════════════════════════════════════
# Handler: contract_checkpoint  (pillar: contracts)
# ══════════════════════════════════════════════════════════════════════

def check_contract_checkpoint(payload, ctx):
    """
    Check a contract checkpoint for freshness-delay and explicit
    contract violations (schema_hash_mismatch, type_violation).
    """
    contract_id = payload.get("contract_id", "?")
    checkpoint_id = payload.get("checkpoint_batch_id", "?")
    b = ctx.baseline

    diff = ctx.tools.contract_diff(contract_id, checkpoint_id)
    if _is_error(diff):
        return Verdict(alert=False, pillar="contracts",
                       reason=f"contract_diff failed: {diff.get('error')}")

    reasons = []
    signals = []

    # 1. Freshness delay
    fd = diff.get("freshness_delay_min")
    if _exceeds(fd, b.get("freshness_delay_max_min")):
        signals.append(1.0)
        reasons.append(f"freshness_delay {fd:.1f}min > max {b['freshness_delay_max_min']:.1f}")

    # 2. Explicit violations
    violations = diff.get("violations", [])
    if violations:
        signals.append(1.2)  # contract violations are strong signals
        reasons.append(f"violations: {', '.join(violations)}")

    if not signals:
        return Verdict(alert=False, pillar="contracts", reason="contract ok")
    confidence = min(1.0, sum(signals) / max(1, len(signals)))
    return Verdict(alert=True, pillar="contracts", confidence=confidence,
                   reason="; ".join(reasons))


# ══════════════════════════════════════════════════════════════════════
# Handler: lineage_run  (pillar: lineage)
# ══════════════════════════════════════════════════════════════════════

def check_lineage_run(payload, ctx):
    """
    Check a lineage run for anomalous duration, missing upstream edges,
    or orphaned downstream counts.

    Strategy:
      - duration_ms vs baseline.lineage_duration_ms_max
      - actual_upstream: if empty list → missing_upstream fault
      - actual_downstream_count: if 0 → orphan_output; track histogram
        in ctx.state to flag statistical anomalies.
    """
    run_id = payload.get("run_id", "?")
    b = ctx.baseline

    g = ctx.tools.lineage_graph_slice(run_id, depth=1)
    if _is_error(g):
        return Verdict(alert=False, pillar="lineage",
                       reason=f"lineage_graph_slice failed: {g.get('error')}")

    reasons = []
    signals = []

    # 1. Duration
    dur = g.get("duration_ms")
    if _exceeds(dur, b.get("lineage_duration_ms_max")):
        signals.append(1.0)
        reasons.append(f"duration {dur:.0f}ms > max {b['lineage_duration_ms_max']:.0f}ms")

    # 2. Upstream — missing entries = missing_upstream
    upstream = g.get("actual_upstream")
    if isinstance(upstream, list):
        up_len = len(upstream)
        # Track upstream lengths; use MODE (most-common) — robust to faults
        up_hist = ctx.state.setdefault("lineage_upstream_lengths", [])
        up_hist.append(up_len)
        if len(up_hist) > 100:
            ctx.state["lineage_upstream_lengths"] = up_hist[-100:]

        if up_len == 0:
            signals.append(1.0)
            reasons.append("empty upstream list (missing_upstream)")
        elif len(up_hist) >= 2:
            # Mode = most frequent value (robust against fault contamination)
            mode = Counter(up_hist[:-1]).most_common(1)[0][0]
            if mode > 0 and up_len < mode:
                signals.append(0.8)
                reasons.append(f"upstream count {up_len} < mode {mode} (missing_upstream)")

    # 3. Downstream — count of 0 = orphan_output
    downstream = g.get("actual_downstream_count")
    if isinstance(downstream, (int, float)):
        if downstream == 0:
            signals.append(1.0)
            reasons.append("downstream_count=0 (orphan_output)")

    if not signals:
        return Verdict(alert=False, pillar="lineage", reason="lineage ok")
    confidence = min(1.0, sum(signals) / max(1, len(signals)))
    return Verdict(alert=True, pillar="lineage", confidence=confidence,
                   reason="; ".join(reasons))


# ══════════════════════════════════════════════════════════════════════
# Handler: feature_materialization  (pillar: ai_infra)
# ══════════════════════════════════════════════════════════════════════

def check_feature_materialization(payload, ctx):
    """
    Check feature materialization for training-serving skew via mean_shift_sigma.
    Cost: 2.0 — skip if budget critically low to avoid overage penalty.
    """
    feature_view = payload.get("feature_view", "?")
    ref = payload.get("batch_id", "?")
    b = ctx.baseline

    if not _budget_safe(ctx, cost=2.0):
        return Verdict(alert=False, pillar="ai_infra", reason="budget conserve: skipped feature_drift")

    drift = ctx.tools.feature_drift(feature_view, ref)
    if _is_error(drift):
        return Verdict(alert=False, pillar="ai_infra",
                       reason=f"feature_drift failed: {drift.get('error')}")

    mss = drift.get("mean_shift_sigma")
    if _exceeds(mss, b.get("feature_mean_shift_sigma_max")):
        # How far beyond threshold determines confidence
        over = mss / b["feature_mean_shift_sigma_max"]
        confidence = min(1.0, 0.7 + 0.1 * over)
        return Verdict(alert=True, pillar="ai_infra", confidence=confidence,
                       reason=f"mean_shift_sigma {mss:.3f} > max {b['feature_mean_shift_sigma_max']:.4f}")
    return Verdict(alert=False, pillar="ai_infra",
                   reason=f"mean_shift_sigma {mss:.3f} ≤ max {b['feature_mean_shift_sigma_max']:.4f}")


# ══════════════════════════════════════════════════════════════════════
# Handler: embedding_batch  (pillar: ai_infra)
# ══════════════════════════════════════════════════════════════════════

def check_embedding_batch(payload, ctx):
    """
    Check an embedding batch for centroid drift and corpus staleness.
    Cost: 2.0 — skip if budget critically low.
    """
    corpus = payload.get("corpus", "?")
    ref = payload.get("chunk_batch_id", "?")
    b = ctx.baseline

    if not _budget_safe(ctx, cost=2.0):
        return Verdict(alert=False, pillar="ai_infra", reason="budget conserve: skipped embedding_drift")

    drift = ctx.tools.embedding_drift(corpus, ref)
    if _is_error(drift):
        return Verdict(alert=False, pillar="ai_infra",
                       reason=f"embedding_drift failed: {drift.get('error')}")

    reasons = []
    signals = []

    # 1. Centroid shift
    cs = drift.get("centroid_shift")
    if _exceeds(cs, b.get("embedding_centroid_shift_max")):
        signals.append(1.0)
        reasons.append(f"centroid_shift {cs:.5f} > max {b['embedding_centroid_shift_max']:.5f}")

    # 2. Average document age
    age = drift.get("avg_doc_age_days")
    if _exceeds(age, b.get("corpus_avg_doc_age_days_max")):
        signals.append(0.9)
        reasons.append(f"avg_doc_age {age:.1f}d > max {b['corpus_avg_doc_age_days_max']:.1f}d")

    if not signals:
        return Verdict(alert=False, pillar="ai_infra", reason="embedding metrics within baseline")
    confidence = min(1.0, sum(signals) / max(1, len(signals)))
    return Verdict(alert=True, pillar="ai_infra", confidence=confidence,
                   reason="; ".join(reasons))
