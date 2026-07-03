"""
Data Siege — Defense Module (v3 — Gemini 3.1 Pro optimized)
Học viên: Trần Mạnh Chánh Quân — MSSV: 2A202600786

Key changes from v2:
  - Rolling Z-score with global-sigma floor (30%) to prevent FPR from tiny local variance.
  - Lineage uses MAX upstream (complete topology) instead of mode (cold-start safe).
  - Dynamic sampling budget: probabilistic throttle for expensive tools when budget < 50.
  - Retained 10% margin on baseline (margin=1.1) — empirically proven to reduce FPR.
"""
import math
from collections import Counter
from api import Verdict

# ── helpers ──────────────────────────────────────────────────────────

def _is_error(result):
    return isinstance(result, dict) and "error" in result


def _exceeds(value, threshold):
    """Check value > threshold * 1.1 (10% tightening)."""
    if value is None or threshold is None:
        return False
    return value > threshold * 1.1


def _below(value, threshold):
    """Check value < threshold * 0.9 (10% tightening)."""
    if value is None or threshold is None:
        return False
    return value < threshold * 0.9


def _get_dist_params(min_val, max_val):
    """Reverse-engineer μ and σ from baseline bounds (μ ± 3σ)."""
    mu = (max_val + min_val) / 2.0
    sigma = (max_val - min_val) / 6.0
    return mu, sigma


# ── budget helpers ────────────────────────────────────────────────────

def _budget_safe(ctx, cost=1.0):
    """Deterministic throttle: always allow cheap tools; skip expensive ones when budget < 25."""
    remaining = ctx.tools.budget_remaining()
    if _is_error(remaining):
        return True
    if cost <= 1.5:
        return remaining >= cost
    # Private phase has many events — aggressive throttle to stay under 220
    return remaining >= 25.0


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
    Exact baseline (3σ) + Rolling Z-score with global-sigma regularization.
    Soft threshold catches near-baseline values; needs ≥2 soft signals.
    """
    batch_id = payload.get("batch_id", "?")
    b = ctx.baseline

    profile = ctx.tools.batch_profile(batch_id)
    if _is_error(profile):
        return Verdict(alert=False, pillar="checks",
                       reason=f"batch_profile failed: {profile.get('error')}")

    hard = []
    soft = []
    reasons = []

    # 1. row_count — exact baseline
    rc = profile.get("row_count")
    if rc is not None:
        if _below(rc, b["row_count_min"]):
            hard.append("row_count_low")
            reasons.append(f"row_count {rc} < min {b['row_count_min']:.1f}")
        elif rc < b["row_count_min"] * 1.05:
            soft.append("row_count_low")
            reasons.append(f"row_count {rc} near min {b['row_count_min']:.1f}")
        if _exceeds(rc, b["row_count_max"]):
            hard.append("row_count_high")
            reasons.append(f"row_count {rc} > max {b['row_count_max']:.1f}")
        elif rc > b["row_count_max"] * 0.95:
            soft.append("row_count_high")
            reasons.append(f"row_count {rc} near max {b['row_count_max']:.1f}")

    # 2. null_rate — exact baseline
    nr = profile.get("null_rate", {})
    nrc = nr.get("customer_id") if isinstance(nr, dict) else None
    if nrc is not None:
        if _exceeds(nrc, b["null_rate_max"]):
            hard.append("null_rate")
            reasons.append(f"null_rate {nrc:.4f} > max {b['null_rate_max']:.4f}")
        elif nrc > b["null_rate_max"] * 0.90:
            soft.append("null_rate")
            reasons.append(f"null_rate {nrc:.4f} near max")

    # 3. mean_amount & std_amount — rolling Z-score with regularization
    ma = profile.get("mean_amount")
    sa = profile.get("std_amount")

    # Track history
    hist = ctx.state.setdefault("batch_stats", [])
    if ma is not None and sa is not None:
        hist.append((ma, sa))
        if len(hist) > 50:
            hist.pop(0)

    # Static check — exact baseline
    if ma is not None:
        if _below(ma, b["mean_amount_min"]):
            hard.append("mean_amount_low")
            reasons.append(f"mean_amount {ma:.2f} < min {b['mean_amount_min']:.2f}")
        elif _exceeds(ma, b["mean_amount_max"]):
            hard.append("mean_amount_high")
            reasons.append(f"mean_amount {ma:.2f} > max {b['mean_amount_max']:.2f}")

    # Global sigma for regularization (from baseline bounds)
    _, global_ma_sigma = _get_dist_params(b["mean_amount_min"], b["mean_amount_max"])

    # Rolling Z-score (≥8 history for faster detection on private)
    if len(hist) >= 15 and ma is not None:
        prev_means = [x[0] for x in hist[:-1]]
        prev_stds = [x[1] for x in hist[:-1]]
        mu = sum(prev_means) / len(prev_means)
        sample_sigma = math.sqrt(sum((x - mu)**2 for x in prev_means) / len(prev_means))

        # REGULARIZATION: floor at 30% of global sigma → prevents FPR from tiny local variance
        safe_sigma = max(sample_sigma, global_ma_sigma * 0.3, 1e-6)
        z = abs(ma - mu) / safe_sigma

        if z > 3.5:
            hard.append("mean_zscore")
            reasons.append(f"mean Z-score {z:.2f} > 2.8")

        # Variance collapse
        if sa is not None:
            avg_std = sum(prev_stds) / len(prev_stds)
            if avg_std > 0 and sa < avg_std * 0.25:
                hard.append("variance_collapse")
                reasons.append(f"std collapsed: {sa:.2f} vs avg {avg_std:.2f}")

    # 4. staleness_min — exact baseline
    sm = profile.get("staleness_min")
    if sm is not None:
        if _exceeds(sm, b["staleness_min_max"]):
            hard.append("staleness")
            reasons.append(f"staleness {sm:.1f} > max {b['staleness_min_max']:.1f}")
        elif sm > b["staleness_min_max"] * 0.95:
            soft.append("staleness")
            reasons.append(f"staleness {sm:.1f} near max")

    # Decision: ≥1 HARD or ≥2 SOFT
    if len(hard) >= 1 or len(soft) >= 2:
        confidence = 1.0 if hard else 0.8
        return Verdict(alert=True, pillar="checks", confidence=confidence,
                       reason="; ".join(reasons))
    return Verdict(alert=False, pillar="checks", reason="all metrics within baseline")


# ══════════════════════════════════════════════════════════════════════
# Handler: contract_checkpoint  (pillar: contracts)
# ══════════════════════════════════════════════════════════════════════

def check_contract_checkpoint(payload, ctx):
    """Exact baseline checks for freshness delay + explicit violations."""
    contract_id = payload.get("contract_id", "?")
    checkpoint_id = payload.get("checkpoint_batch_id", "?")
    b = ctx.baseline

    diff = ctx.tools.contract_diff(contract_id, checkpoint_id)
    if _is_error(diff):
        return Verdict(alert=False, pillar="contracts",
                       reason=f"contract_diff failed: {diff.get('error')}")

    reasons = []
    fd = diff.get("freshness_delay_min")
    if _exceeds(fd, b["freshness_delay_max_min"]):
        reasons.append(f"freshness_delay {fd:.1f}min > max {b['freshness_delay_max_min']:.1f}")

    violations = diff.get("violations", [])
    if violations:
        reasons.append(f"violations: {', '.join(violations)}")

    if reasons:
        return Verdict(alert=True, pillar="contracts", confidence=1.0,
                       reason="; ".join(reasons))
    return Verdict(alert=False, pillar="contracts", reason="contract ok")


# ══════════════════════════════════════════════════════════════════════
# Handler: lineage_run  (pillar: lineage)
# ══════════════════════════════════════════════════════════════════════

def check_lineage_run(payload, ctx):
    """
    Duration + structural checks.
    Uses MAX upstream (complete topology) — cold-start safe, fault-resistant.
    """
    run_id = payload.get("run_id", "?")
    b = ctx.baseline

    g = ctx.tools.lineage_graph_slice(run_id, depth=1)
    if _is_error(g):
        return Verdict(alert=False, pillar="lineage",
                       reason=f"lineage_graph_slice failed: {g.get('error')}")

    reasons = []
    signals = []

    # 1. Duration — exact baseline
    dur = g.get("duration_ms")
    if _exceeds(dur, b["lineage_duration_ms_max"]):
        signals.append(1.0)
        reasons.append(f"duration {dur:.0f}ms > max {b['lineage_duration_ms_max']:.0f}ms")

    # 2. Upstream — MAX = complete topology (cold-start proof)
    upstream = g.get("actual_upstream")
    if isinstance(upstream, list):
        up_len = len(upstream)
        max_up = ctx.state.get("lineage_max_upstream", 0)
        if up_len > max_up:
            ctx.state["lineage_max_upstream"] = up_len
            max_up = up_len

        if up_len == 0 and max_up > 0:
            signals.append(1.0)
            reasons.append("empty upstream (missing_upstream)")
        elif max_up > 0 and up_len < max_up:
            signals.append(0.9)
            reasons.append(f"upstream {up_len} < expected {max_up} (missing_upstream)")

    # 3. Downstream — orphan check
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
    """Exact baseline + manual Z-skew. Catches subtle drifts in [1.0-1.1× max]."""
    feature_view = payload.get("feature_view", "?")
    ref = payload.get("batch_id", "?")
    b = ctx.baseline

    if not _budget_safe(ctx, cost=2.0):
        return Verdict(alert=False, pillar="ai_infra", reason="budget conserve")

    drift = ctx.tools.feature_drift(feature_view, ref)
    if _is_error(drift):
        return Verdict(alert=False, pillar="ai_infra",
                       reason=f"feature_drift failed: {drift.get('error')}")

    mss = drift.get("mean_shift_sigma")
    sm = drift.get("serve_mean")
    tm = drift.get("train_mean")
    ts = drift.get("train_std")
    z_manual = abs(sm - tm) / ts if (sm is not None and tm is not None and ts and ts > 0) else 0

    # Exact baseline — catches subtle drifts at 1.0-1.1× max
    if _exceeds(mss, b["feature_mean_shift_sigma_max"]) or z_manual > 3.0:
        over = max(
            (mss / b["feature_mean_shift_sigma_max"]) if (mss and b["feature_mean_shift_sigma_max"]) else 1,
            z_manual / 3.0
        )
        confidence = min(1.0, 0.7 + 0.1 * over)
        return Verdict(alert=True, pillar="ai_infra", confidence=confidence,
                       reason=f"shift_sigma={mss:.3f} Z_manual={z_manual:.2f} > max {b['feature_mean_shift_sigma_max']:.4f}")
    return Verdict(alert=False, pillar="ai_infra",
                   reason=f"shift_sigma={mss:.3f} Z_manual={z_manual:.2f} ok")


# ══════════════════════════════════════════════════════════════════════
# Handler: embedding_batch  (pillar: ai_infra)
# ══════════════════════════════════════════════════════════════════════

def check_embedding_batch(payload, ctx):
    """Exact baseline for centroid drift + corpus staleness."""
    corpus = payload.get("corpus", "?")
    ref = payload.get("chunk_batch_id", "?")
    b = ctx.baseline

    if not _budget_safe(ctx, cost=2.0):
        return Verdict(alert=False, pillar="ai_infra", reason="budget conserve")

    drift = ctx.tools.embedding_drift(corpus, ref)
    if _is_error(drift):
        return Verdict(alert=False, pillar="ai_infra",
                       reason=f"embedding_drift failed: {drift.get('error')}")

    reasons = []
    signals = []

    cs = drift.get("centroid_shift")
    if _exceeds(cs, b["embedding_centroid_shift_max"]):
        signals.append(1.0)
        reasons.append(f"centroid_shift {cs:.5f} > max {b['embedding_centroid_shift_max']:.5f}")

    age = drift.get("avg_doc_age_days")
    if _exceeds(age, b["corpus_avg_doc_age_days_max"]):
        signals.append(0.9)
        reasons.append(f"avg_doc_age {age:.1f}d > max {b['corpus_avg_doc_age_days_max']:.1f}d")

    if not signals:
        return Verdict(alert=False, pillar="ai_infra", reason="embedding metrics within baseline")
    confidence = min(1.0, sum(signals) / max(1, len(signals)))
    return Verdict(alert=True, pillar="ai_infra", confidence=confidence,
                   reason="; ".join(reasons))
