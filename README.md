# Personal Finance Assistant

An AI finance agent for FinTechathon 2026, International Track, Topic A (Personal Finance Assistant). Ask it about your spending, get a cashflow projection, catch spending spikes, and get savings suggestions. It can propose budget changes, but it never applies one without you.

## Status

- **Built:** monthly summaries, category spending, transactions, budget status, bills, duplicate detection, cashflow projection, spike detection, savings recommendations, conversation memory, budget changes with terminal approval, logging, and an 18-case evaluation.
- **In progress:** prompt-injection defenses, bookkeeping with approval, the web interface, technical documentation, and the security self-assessment.

## Run it

Requirements: Python 3.10 or newer, and a Gemini API key from Google AI Studio.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Create a `.env` file in the project root:

```
GEMINI_API_KEY=your-key-here
```

Start the chat:

```bash
python main.py
```

Commands inside the chat:

- `/pending`: list budget changes waiting for approval
- `/apply <proposal_id>`: review a change and type exactly `yes` to apply it
- `/reset`: clear the conversation memory
- `exit`: quit

Try: "How much did I spend on groceries in July 2026?", then "What about August?". Or: "Set my dining budget to 50.", then `/pending`.

## Test and evaluate

```bash
python -m pytest -v            # unit tests
python eval/run_eval.py        # 18-case evaluation, uses the live Gemini API
```

The evaluation can show retries when Gemini is under load. The simulated date is 2026-08-31. Override it with `FINANCE_AS_OF_DATE=YYYY-MM-DD`.

## Project layout

- `data/`: simulated transactions, bills, budgets, and account. This is sandbox data, not real financial information.
- `src/`: tools, permissions, approvals, agent loop, prompts, and logger
- `eval/`: evaluation questions and runner
- `tests/`: unit tests
- `docs/evidence/`: execution evidence and its index

## How the safety model works

- Read tools run without approval.
- The propose tool creates a pending change. It changes nothing.
- The apply step runs only from the `/apply` command in your terminal, and only after you type exactly `yes`.
- The model has no tool that can apply a change. A tool call to apply one is blocked, and the block is logged.
- API keys are redacted from logs. Keep `.env` out of version control.

## Limits

- Data is simulated, and the balance is a sandbox figure.
- Answers are informational. Recommendations are general suggestions, not professional financial advice.
- If the model hits its step limit, the chat shows the fallback message as a normal answer.
- The chat’s error message was tested with a simulated model failure, not a live rate-limit error.