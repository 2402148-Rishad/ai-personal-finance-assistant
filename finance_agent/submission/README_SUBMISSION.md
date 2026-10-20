# FinTechathon 2026 Submission: Personal Finance Assistant

**Track**: International Track, Topic A (Personal Finance Assistant)  
**Repository**: https://github.com/2402148-Rishad/ai-personal-finance-assistant  
**Live Deployed Application**: https://ai-personal-finance-assistant-acceyufjoyulunmsa5rblo.streamlit.app/  
**Demo Video**: https://drive.google.com/drive/folders/1f3FfFpHvDyiIKkHZQZEG0ux6tSCrn_2q?usp=sharing  
**Presentation Deck**: https://drive.google.com/drive/folders/1RLlQI39YNkpjz1jLwzcXtcw4R7ToOcoL  


---

## 1. How to Run Locally

### Prerequisites
- Python 3.10 or newer
- Gemini API Key from Google AI Studio

### Local Setup
```bash
# Clone and enter the repository
git clone https://github.com/2402148-Rishad/ai-personal-finance-assistant.git
cd ai-personal-finance-assistant/finance_agent

# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate          # On Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Configure API Key in .env
echo GEMINI_API_KEY=your_gemini_api_key_here > .env

# Launch the Streamlit Web Application
streamlit run app.py
```
*Alternatively, run the interactive terminal chat via `python main.py`.*

### Running Automated Tests & Evaluations
All tests run offline without consuming live Gemini API quota:
```bash
python -m pytest -q            # Runs all 275 tests across 43 test files
python eval/run_eval.py        # Runs 31 benchmark cases in mock mode
python eval/run_scenarios.py   # Runs 23 multi-step golden and adversarial scenarios
python docs/check_docs.py      # Verifies consistency of all documentation
```

---

## 2. Documentation Directory Map

This submission folder includes verbatim copies of the core project documentation:

1. **`TECHNICAL.md`** (*Architecture & Engineering Blueprint*):
   - Detailed component breakdown, permission tier architecture, ContextVar session workspace isolation, atomic file operations (`os.replace`), and append-only audit logging.

2. **`SECURITY.md`** (*Security Self-Assessment & Governance*):
   - Self-assessment adhering to zero-trust principles.
   - Comprehensive threat matrix, human-in-the-loop approval gates (low-risk "yes" vs high-risk "CONFIRM"), repository secret scan results, and adversarial evaluation matrices (ADV01–ADV18 and adv_live_01–06).

3. **`FEATURES.md`** (*Capabilities & Verification Matrix*):
   - Exhaustive catalogue of every Topic A feature, linking capabilities directly to code locations, sample prompts, tool schemas, and automated test suites.

4. **`USER_GUIDE.md`** (*User Manual*):
   - Guide for first-time users explaining how to interact with the 4 UI workspaces (Chat, Overview, Ledger & Budgets, Pending & Audit), how approvals and undos operate, out-of-scope refusals, and how to read the "How I got this" provenance panel.

5. **`DEMO_SCRIPT.md`** (*5-Minute Presentation Script*):
   - Minute-by-minute walkthrough utilizing only automated-test-covered prompts, complete with visual UI cues, talking points, and contingency fallbacks for network latency and daily quota limits.

---

## 3. Execution Evidence

The `evidence/` directory contains complete execution transcripts, audit logs, and benchmark result records:

1. **`evidence/demo_session/`**:
   - Complete scripted walkthrough of `DEMO_SCRIPT.md` prompts through the agent pipeline using the live model (`gemini-3.5-flash-lite`), totaling 10 model calls.
   - Contains:
     - `run_demo_live.py`: Script that executed the walkthrough and generated the session evidence.
     - `transcript.json` and `transcript.md`: Full multi-turn dialogue with exact arguments, tool outputs, and approval resolutions.
     - `audit.jsonl`: Immutable audit log of the human approval gate execution.
     - `proposals.json`: Post-run proposals ledger.
     - `README.md`: Run metadata and summary.

2. **Benchmark & Evaluation Result Files**:
   - **`evidence/2026-10-19-live-final-2.json`**: **Final live benchmark** evaluation results.
   - `evidence/2026-10-19-live-final.json`: Earlier live benchmark run kept for history.
   - `evidence/2026-10-19-live.json`: Earlier live benchmark run kept for history.
   - `evidence/2026-10-19-mock.json`: Mock evaluation benchmark results.
   - `evidence/2026-10-18-mock.json`: Earlier mock evaluation run kept for history.
   - `evidence/2026-10-19-scenarios-mock.json`: 23 multi-step golden and adversarial scenario results.
   - `evidence/live_adversarial.json`: Live adversarial test results.

