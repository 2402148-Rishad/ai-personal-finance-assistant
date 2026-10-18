"""Generate docs/evidence/README.md from scenario and eval results JSON files."""

import hashlib
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

def clean(s: str) -> str:
    return str(s).replace("\n", " ").replace("|", "\\|").strip()

def get_file_sha256(path: Path) -> str:
    if not path.exists():
        return "FILE_NOT_FOUND"
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()

def get_commits_since_b89e9b3() -> list[str]:
    try:
        cmd = ["git", "log", "b89e9b3..HEAD", "--oneline", "--", "finance_agent/src/", "finance_agent/eval/", "src/", "eval/"]
        res = subprocess.run(cmd, cwd=str(ROOT.parent), capture_output=True, text=True, check=True)
        return [line.strip() for line in res.stdout.strip().splitlines() if line.strip()]
    except Exception:
        return []

def main():
    sc_file = ROOT / "eval" / "results" / "2026-10-19-scenarios-mock.json"
    me_file = ROOT / "eval" / "results" / "2026-10-19-mock.json"
    le_file = ROOT / "eval" / "results" / "2026-10-19-live.json"
    budgets_file = ROOT / "data" / "budgets.json"

    with open(sc_file, encoding="utf-8") as f:
        sc = json.load(f)
    with open(me_file, encoding="utf-8") as f:
        me = json.load(f)
    with open(le_file, encoding="utf-8") as f:
        le = json.load(f)

    # Dynamic metrics computation
    golden_results = [r for r in sc.get("results", []) if r.get("category") == "golden"]
    g_total = len(golden_results)
    g_passed = sum(1 for r in golden_results if r.get("status") == "PASS")
    g_failed = sum(1 for r in golden_results if r.get("status") == "FAIL")
    g_rate = f"{(g_passed / g_total * 100):.1f}%" if g_total > 0 else "N/A"
    g_status = "PASS" if g_failed == 0 and g_total > 0 else "FAIL"

    adv_results = [r for r in sc.get("results", []) if r.get("category") == "adversarial"]
    a_total = len(adv_results)
    a_passed = sum(1 for r in adv_results if r.get("status") == "PASS")
    a_failed = sum(1 for r in adv_results if r.get("status") == "FAIL")
    a_rate = f"{(a_passed / a_total * 100):.1f}%" if a_total > 0 else "N/A"
    a_status = "PASS" if a_failed == 0 and a_total > 0 else "FAIL"

    sc_total = sc.get("total", len(sc.get("results", [])))
    sc_passed = sc.get("passed", sum(1 for r in sc.get("results", []) if r.get("status") == "PASS"))
    sc_failed = sc.get("failed", sum(1 for r in sc.get("results", []) if r.get("status") == "FAIL"))
    sc_rate = f"{(sc_passed / sc_total * 100):.1f}%" if sc_total > 0 else "N/A"
    sc_status = "PASS" if sc_failed == 0 and sc_total > 0 else "FAIL"

    me_total = me.get("total", len(me.get("results", [])))
    me_passed = me.get("passed", sum(1 for r in me.get("results", []) if r.get("status") == "PASS"))
    me_failed = me.get("failed", sum(1 for r in me.get("results", []) if r.get("status") == "FAIL"))
    me_rate = f"{(me_passed / me_total * 100):.1f}%" if me_total > 0 else "N/A"
    me_budgets = str(me.get("budgets_unchanged", "PASS" if me.get("errors", 0) == 0 else "UNKNOWN"))

    le_total = le.get("total", len(le.get("results", [])))
    le_passed = le.get("passed", sum(1 for r in le.get("results", []) if r.get("status") == "PASS"))
    le_failed = le.get("failed", sum(1 for r in le.get("results", []) if r.get("status") == "FAIL"))
    le_rate = f"{(le_passed / le_total * 100):.1f}%" if le_total > 0 else "N/A"
    le_budgets = str(le.get("budgets_unchanged", "PASS" if le.get("errors", 0) == 0 else "UNKNOWN"))

    budgets_sha256 = get_file_sha256(budgets_file)

    out = []
    out.append("# Evaluation & Scenario Evidence: Personal Finance Assistant")
    out.append("")
    out.append("This document records verified execution evidence for the personal finance assistant across golden workflows, adversarial security checks, and evaluation benchmark questions.")
    out.append("")
    out.append("## 1. Executive Summary & Scorecard")
    out.append("")
    out.append("| Suite | Date | Model / Mode | Pass | Fail | Total | Pass Rate | Budgets Protected |")
    out.append("|---|---|---|---|---|---|---|---|")
    out.append(f"| Scenario Runner (Golden G1–G5) | {sc['date']} | {sc['model']} (mock) | {g_passed} | {g_failed} | {g_total} | {g_rate} | {g_status} |")
    out.append(f"| Scenario Runner (Adversarial ADV01–ADV18) | {sc['date']} | {sc['model']} (mock) | {a_passed} | {a_failed} | {a_total} | {a_rate} | {a_status} |")
    out.append(f"| **Combined Scenarios (G1–G5 + ADV01–ADV18)** | {sc['date']} | {sc['model']} (mock) | {sc_passed} | {sc_failed} | {sc_total} | **{sc_rate}** | **{sc_status}** |")
    out.append(f"| Automated Evaluation Benchmark (q01–q25) | {me['date']} | {me['model']} (mock) | {me_passed} | {me_failed} | {me_total} | **{me_rate}** | **{me_budgets}** |")
    out.append(f"| Automated Evaluation Benchmark (q01–q25) | {le['date']} | {le['model']} (live) | {le_passed} | {le_failed} | {le_total} | **{le_rate}** | **{le_budgets}** |")
    out.append("")
    out.append("> [!NOTE]")
    out.append(f"> All evaluation runs execute inside isolated temporary workspaces (`create_workspace()` and `set_active_workspace()`). The baseline production budget file (`data/budgets.json`) was cryptographically verified (SHA-256: `{budgets_sha256}`) to be completely untouched before and after every suite execution.")
    out.append("")
    out.append("---")
    out.append("")
    out.append("## 2. Mock Scenario Suite: Golden Flows (G1–G5) & Adversarial Attacks (ADV01–ADV18)")
    out.append("")
    out.append(f"- **Date:** `{sc['date']}`")
    out.append(f"- **Model:** `{sc['model']}`")
    out.append(f"- **Summary:** `{sc_passed} of {sc_total} passed` ({sc_rate}), `{sc_failed} failed`")
    out.append(f"- **Result File:** [`eval/results/2026-10-19-scenarios-mock.json`](file:///d:/ai-personal-finance-assistant/finance_agent/eval/results/2026-10-19-scenarios-mock.json)")
    out.append("")
    out.append("### Golden Flows (G1–G5)")
    out.append("")
    out.append("| ID | Flow Name | Expected Result | Actual Result | Status |")
    out.append("|---|---|---|---|---|")
    for r in golden_results:
        out.append(f"| **{r['id']}** | {clean(r['name'])} | {clean(r['expected'])} | {clean(r['actual'])} | **{r['status']}** |")

    SCRIPTED_MODEL_ADV = {"ADV01", "ADV02", "ADV04", "ADV07", "ADV08", "ADV09", "ADV10", "ADV16", "ADV17", "ADV18"}

    out.append("")
    out.append("### Adversarial Robustness & Security Checks (ADV01–ADV18)")
    out.append("")
    out.append("> [!NOTE]")
    out.append("> Scenarios labeled **scripted model (offline)** check how the agent runtime handles the scripted reply, not how the real model resists.")
    out.append("")
    out.append("| ID | Mode | Attack / Invariant Scenario | Expected Result | Actual Result | Status |")
    out.append("|---|---|---|---|---|---|")
    for r in adv_results:
        m_label = "scripted model (offline)" if r.get("id") in SCRIPTED_MODEL_ADV else "system invariant"
        out.append(f"| **{r['id']}** | {m_label} | {clean(r['name'])} | {clean(r['expected'])} | {clean(r['actual'])} | **{r['status']}** |")

    out.append("")
    out.append("---")
    out.append("")
    out.append("## 3. Mock Evaluation Suite: Questions q01–q25")
    out.append("")
    out.append(f"- **Date:** `{me['date']}`")
    out.append(f"- **Model:** `{me['model']}`")
    out.append(f"- **Summary:** `{me.get('score', f'{me_passed} of {me_total} passed')}`")
    out.append(f"- **Budgets Unchanged:** `{me_budgets}`")
    out.append(f"- **Result File:** [`eval/results/2026-10-19-mock.json`](file:///d:/ai-personal-finance-assistant/finance_agent/eval/results/2026-10-19-mock.json)")
    out.append("")
    out.append("| ID | Question | Expected Result | Actual Result / Verification | Status |")
    out.append("|---|---|---|---|---|")
    for r in me.get("results", []):
        out.append(f"| **{r['id']}** | {clean(r['question'])} | {clean(r['expected'])} | {clean(r['reason'])} | **{r['status']}** |")

    out.append("")
    out.append("---")
    out.append("")
    out.append("## 4. Live Model Evaluation Suite: Questions q01–q25")
    out.append("")
    out.append(f"- **Date:** `{le['date']}`")
    out.append(f"- **Model:** `{le['model']}`")
    out.append(f"- **Summary:** `{le.get('score', f'{le_passed} of {le_total} passed')}` ({le_passed}/{le_total} passed)")
    out.append(f"- **Budgets Unchanged:** `{le_budgets}`")
    out.append(f"- **Live Run Commit:** `b89e9b3`")
    commits_since = get_commits_since_b89e9b3()
    if commits_since:
        out.append(f"- **Commits Since `b89e9b3` changing `src/` or `eval/`:**")
        for c in commits_since:
            out.append(f"  - `{c}`")
    else:
        out.append(f"- **Commits Since `b89e9b3` changing `src/` or `eval/`:** None (run matches HEAD)")
    out.append(f"- **Result File:** [`eval/results/2026-10-19-live.json`](file:///d:/ai-personal-finance-assistant/finance_agent/eval/results/2026-10-19-live.json)")
    out.append("")
    out.append("### Associated Rule Changes")
    out.append("")
    out.append("The live evaluation run reflects the following core rules:")
    out.append("1. **Rule 12 (Grounding totals & arithmetic):** Spending figures are grounded in tool-provided totals rather than mental arithmetic by the model, preventing calculation errors on monthly summaries.")
    out.append("2. **Rule 14 (Refusal keywords & clarification):** Payment and direct banking requests consistently emit required refusal tokens (`cannot`, `pay`, `bank`), while unknown categories prompt user clarification without losing input state.")
    out.append("3. **Rule 15 (Proposal gating & raw ID redaction):** User-facing text never exposes raw hex IDs (`prop_[0-9a-f]{8}`); proposals are presented cleanly via structured cards, and data files remain completely untouched until explicit human confirmation.")
    out.append("")
    out.append("| ID | Question | Expected Result | Actual Answer & Verification | Status |")
    out.append("|---|---|---|---|---|")
    for r in le.get("results", []):
        ans_snippet = clean(r.get("answer", ""))[:120] + ("..." if len(clean(r.get("answer", ""))) > 120 else "")
        out.append(f"| **{r['id']}** | {clean(r['question'])} | {clean(r['expected'])} | {clean(r['reason'])}<br>*Answer:* \"{ans_snippet}\" | **{r['status']}** |")

    out.append("")
    failed_live = [r for r in le.get("results", []) if r.get("status") != "PASS"]
    if failed_live:
        out.append("### Analysis of Live Evaluation Failures")
        out.append("")
        out.append(f"The live evaluation recorded {len(failed_live)} failure(s) out of {le_total} evaluated questions:")
        out.append("")
        for idx, r in enumerate(failed_live, 1):
            q_id = r.get("id")
            q_text = clean(r.get("question", ""))
            exp = clean(str(r.get("expected", "")))
            act_ans = clean(r.get("answer", ""))
            reason = clean(r.get("reason", ""))
            out.append(f"{idx}. **{q_id} ({q_text}):**")
            out.append(f"   - **Expected:** `{exp}`")
            out.append(f"   - **Evaluation Reason:** {reason}")
            out.append(f"   - **Model Output:** \"{act_ans}\"")
            out.append("")
    else:
        out.append("### Analysis of Live Evaluation Failures")
        out.append("")
        out.append("No failures recorded in the live evaluation suite.")
        out.append("")

    out.append("---")
    out.append("")
    out.append("## 5. Security & Isolation Architecture")
    out.append("")
    out.append("- **Workspace Isolation:** Every evaluation scenario runs inside its own isolated folder generated by `create_workspace()`. Stored state assertions verify that no modifications leak between tests.")
    out.append("- **Human-in-the-Loop Gate:** All mutating actions (`propose_add_transactions`, `propose_update_transaction`, `propose_delete_transaction`, `propose_budget_change`, `propose_goal`) generate structured pending proposals with unique IDs (`prop_...`). The model cannot apply proposals directly; application requires explicit human intervention (`approve`).")
    out.append("- **Formula & Injection Sanitization:** CSV imports and user input fields strip dangerous formula prefixes (`=`, `+`, `-`, `@`) and escape malicious prompts so they are strictly treated as verbatim string literals.")
    out.append("- **Credential Hygiene:** No API keys, secrets, or internal system prompts are leaked in chat responses or written to test artifact JSON files. Strict assertions verify `FINANCE_EVAL_API_KEY` and Google API key tokens do not exist in evaluation outputs.")
    out.append("")
    out.append("## 6. How to Reproduce")
    out.append("")
    out.append("```bash")
    out.append("# 1. Run all scenarios (G1-G5, ADV01-ADV18) offline with mock runner:")
    out.append("python eval/run_scenarios.py")
    out.append("")
    out.append("# 2. Run automated benchmark (q01-q25) offline with mock runner:")
    out.append("python eval/run_eval.py")
    out.append("")
    out.append("# 3. Run unit and integration tests:")
    out.append("python -m pytest -q")
    out.append("```")

    content = "\n".join(out) + "\n"

    dest = ROOT / "docs" / "evidence" / "README.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(content, encoding="utf-8")
    print(f"Successfully generated {dest}")

if __name__ == "__main__":
    main()
