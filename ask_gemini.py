#!/usr/bin/env python3
"""
Gửi logic defense.py hiện tại lên Gemini để xin đề xuất cải thiện.
Dùng REST API (không cần cài SDK). Đọc API key từ file .env.
"""
import os
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent

# ── Load .env ─────────────────────────────────────────────────────────
env_path = ROOT / ".env"
if env_path.exists():
    for line in env_path.read_text().strip().split("\n"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, val = line.split("=", 1)
            os.environ[key.strip()] = val.strip().strip('"').strip("'")

API_KEY = os.getenv("GOOGLE_API_KEY", "")
if not API_KEY or API_KEY == "your_api_key_here":
    print("ERROR: Vui lòng điền GOOGLE_API_KEY vào file .env trước khi chạy!")
    exit(1)

# ── Gather context ────────────────────────────────────────────────────
defense_code = (ROOT / "solution" / "defense.py").read_text()
practice_report = json.loads((ROOT / "solution" / "practice_report.json").read_text())
public_report = json.loads((ROOT / "solution" / "public_report.json").read_text())
baselines = json.loads((ROOT / "data" / "baselines.json").read_text())
toolkit_api = (ROOT / "docs" / "TOOLKIT_API.md").read_text()
fault_pillars = (ROOT / "docs" / "FAULT_PILLARS.md").read_text()

# ── Build prompt ──────────────────────────────────────────────────────
prompt = (
    "You are an expert AI/ML engineer reviewing a data pipeline fault detection system.\n\n"
    "## SYSTEM CONTEXT\n\n"
    "This is a \"Data Siege\" defense assignment. A stream of pipeline events flows through\n"
    "defense.py. Each event must be classified as FAULT (alert=True) or CLEAN (alert=False).\n\n"
    "### Score formula:\n"
    "score = 100 * (0.5*TPR - 0.3*FPR - 0.2*min(cost_overage, 1))\n\n"
    "### Budget: 220 credits total. Each tool call costs credits.\n\n"
    "### Event types & tools:\n" + toolkit_api + "\n\n"
    "### Fault pillars:\n" + fault_pillars + "\n\n"
    "### Baseline constants (mean ± 3σ from clean stream):\n"
    + json.dumps(baselines, indent=2) + "\n\n"
    "---\n\n"
    "## CURRENT RESULTS\n\n"
    "### Practice phase:\n"
    f"- Score: {practice_report['result']['score']}/50\n"
    f"- TPR: {practice_report['result']['tpr']} ({practice_report['result']['n_faulty']} faults)\n"
    f"- FPR: {practice_report['result']['fpr']} ({practice_report['result']['n_clean']} clean)\n"
    f"- Cost: {practice_report['result']['cost_ledger']}/{practice_report['result']['budget']}\n"
    "- All pillars: HIGH\n\n"
    "### Public phase:\n"
    f"- Score: {public_report['result']['score']}/50\n"
    f"- TPR: {public_report['result']['tpr']} ({public_report['result']['n_faulty']} faults)\n"
    f"- FPR: {public_report['result']['fpr']} ({public_report['result']['n_clean']} clean)\n"
    f"- Cost: {public_report['result']['cost_ledger']}/{public_report['result']['budget']}\n"
    "- All pillars: HIGH\n\n"
    "### Gap: 4 faults undetected, 1 false positive on Public.\n"
    "Private phase will have MORE subtle faults — need to generalize better.\n\n"
    "---\n\n"
    "## CURRENT DEFENSE LOGIC\n\n"
    "```python\n" + defense_code + "\n```\n\n"
    "---\n\n"
    "## YOUR TASK\n\n"
    "Analyze the current defense logic and suggest SPECIFIC, ACTIONABLE improvements to:\n"
    "1. Catch the 4 remaining undetected faults (improve TPR from 0.8974)\n"
    "2. Eliminate the 1 remaining false positive (improve FPR from 0.0083)\n"
    "3. Keep cost within 220 budget\n\n"
    "For each suggestion, explain:\n"
    "- WHY the current logic misses it\n"
    "- WHAT specific code change to make\n"
    "- WHICH lines/functions to modify\n"
    "- Risk of increasing FPR or cost\n\n"
    "Focus on:\n"
    "- Statistical approaches beyond simple threshold comparison\n"
    "- Using std_amount, train_std, and other available metrics for Z-score based detection\n"
    "- Better use of ctx.state for cross-event pattern detection\n"
    "- Adaptive thresholding that works across phases (anti-overfit)\n"
    "- Budget optimization strategies\n\n"
    "Reply in Vietnamese if possible, or English. Be specific with code snippets."
)

# ── Call Gemini API ───────────────────────────────────────────────────
# Try multiple model names — first success wins
MODELS = [
    "gemini-3.1-pro-preview",
    "gemini-3.5-flash",
    "gemini-2.5-pro",
    "gemini-pro",
]

for MODEL in MODELS:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={API_KEY}"

    body = json.dumps({
        "contents": [{
            "parts": [{"text": prompt}]
        }],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 8192,
            "topP": 0.95,
        }
    }).encode("utf-8")

    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})

    print(f"Thử model: {MODEL}...")

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode())

        text = result["candidates"][0]["content"]["parts"][0]["text"]

        output_path = ROOT / "gemini_suggestions.md"
        output_path.write_text(f"# Gemini Suggestions for Defense Improvement\n\n"
                               f"**Model:** {MODEL}\n"
                               f"**Date:** 2026-07-03\n\n"
                               f"---\n\n{text}")

        print("=" * 70)
        print(text)
        print("=" * 70)
        print(f"\n✅ Đã lưu vào: {output_path}")
        break

    except urllib.error.HTTPError as e:
        err = e.read().decode()
        print(f"  ❌ HTTP {e.code}: {err[:200]}")
        continue
    except Exception as e:
        print(f"  ❌ Error: {e}")
        continue
else:
    print("\n❌ Tất cả model đều thất bại. Kiểm tra API key hoặc thử model khác.")
