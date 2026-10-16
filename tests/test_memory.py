"""Unit tests for conversation memory, history trimming, /reset command, and step limits."""

import json
from unittest.mock import MagicMock
import pytest
from google.genai import types

from src.agent import run_agent, trim_history, AgentResult, _has_function_call, _has_function_response
import src.logger as logger_module
import main as main_module


@pytest.fixture(autouse=True)
def isolate_logs(tmp_path, monkeypatch):
    """Isolate logs directory to tmp_path for all tests in this file."""
    monkeypatch.setattr(logger_module, "LOGS_DIR", tmp_path)
    return tmp_path


def test_follow_up_question_produces_august_tool_call(monkeypatch):
    """6.1) A follow-up question ('What about August?' after a July question) produces a tool call with month 2026-08."""
    # We will simulate two consecutive turns with mock Gemini responses:
    # Turn 1: User asks July question -> Model calls spending_by_category for 2026-07 -> Model returns July answer
    # Turn 2: User asks "What about August?" with history -> Model calls spending_by_category for 2026-08 -> Model returns August answer

    class MockFunctionCall:
        def __init__(self, name, args):
            self.name = name
            self.args = args

    class MockModelResponse:
        def __init__(self, text=None, function_calls=None):
            self.text = text
            self.function_calls = function_calls or []
            parts = []
            if function_calls:
                for fc in function_calls:
                    parts.append(types.Part.from_function_call(name=fc.name, args=fc.args))
            if text:
                parts.append(types.Part.from_text(text=text))
            self.candidates = [MagicMock(content=types.Content(role="model", parts=parts))]

    turn_counter = 0

    def mock_generate_content(model, contents, config):
        nonlocal turn_counter
        turn_counter += 1

        # Check last message in contents
        last_msg = contents[-1]
        last_part = last_msg.parts[0] if last_msg.parts else None

        if getattr(last_part, "text", None) == "How much did I spend on groceries in July 2026?":
            # Turn 1 Step 1: Model decides to call spending_by_category for 2026-07
            return MockModelResponse(
                function_calls=[MockFunctionCall("spending_by_category", {"category": "Groceries", "month": "2026-07"})]
            )
        elif getattr(last_part, "function_response", None) is not None:
            # Check if this response was for July or August
            fr_name = last_part.function_response.name
            fr_data = last_part.function_response.response
            if "2026-07" in str(fr_data) or turn_counter == 2:
                # Turn 1 Step 2: Final answer for July
                return MockModelResponse(text="You spent $500.00 on groceries in July 2026.")
            else:
                # Turn 2 Step 2: Final answer for August
                return MockModelResponse(text="You spent $450.00 on groceries in August 2026.")
        elif getattr(last_part, "text", None) == "What about August?":
            # Turn 2 Step 1: Model sees conversation history and decides to call spending_by_category for 2026-08
            return MockModelResponse(
                function_calls=[MockFunctionCall("spending_by_category", {"category": "Groceries", "month": "2026-08"})]
            )
        else:
            return MockModelResponse(text="I am not sure.")

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = mock_generate_content
    monkeypatch.setattr("src.agent.genai.Client", lambda api_key=None: mock_client)

    # Execute Turn 1
    result1 = run_agent("How much did I spend on groceries in July 2026?", history=[])
    assert result1.status == "ok"
    assert "July" in result1.answer or "500" in result1.answer
    assert len(result1.history) > 0

    # Execute Turn 2 with history
    result2 = run_agent("What about August?", history=result1.history)
    assert result2.status == "ok"
    assert len(result2.tool_calls) >= 1
    # Check that tool call arguments has month == 2026-08
    months = [tc["arguments"].get("month") for tc in result2.tool_calls if "month" in tc.get("arguments", {})]
    assert "2026-08" in months


def test_history_trimmed_to_10_turns_never_leaves_orphaned_function_response():
    """6.2) History is trimmed to 10 turns and never leaves a function response without its function call."""
    # Construct a 12-message history where:
    # index 0: User initial text
    # index 1: Model function_call
    # index 2: User function_response
    # index 3: Model text answer
    # index 4..11: 8 alternating user/model text turns
    history = [
        types.Content(role="user", parts=[types.Part.from_text(text="User Q0")]),
        types.Content(role="model", parts=[types.Part.from_function_call(name="get_monthly_summary", args={"month": "2026-06"})]),
        types.Content(role="user", parts=[types.Part.from_function_response(name="get_monthly_summary", response={"total": 100})]),
        types.Content(role="model", parts=[types.Part.from_text(text="Total was 100")]),
    ]
    for i in range(1, 5):
        history.append(types.Content(role="user", parts=[types.Part.from_text(text=f"User Q{i}")]))
        history.append(types.Content(role="model", parts=[types.Part.from_text(text=f"Model A{i}")]))

    assert len(history) == 12

    # A naive slice [-10:] would start at index 2, which is the function_response,
    # separating it from index 1 (the function_call) and leaving it orphaned.
    naive_slice = history[-10:]
    assert _has_function_response(naive_slice[0]) is True

    # With trim_history, the history is limited to 10 turns and never leaves a function response without its call
    trimmed = trim_history(history, max_turns=10)

    # 1. Trimmed history must be <= 10 turns
    assert len(trimmed) <= 10

    # 2. Never leave a function response without its function call
    for idx, msg in enumerate(trimmed):
        if _has_function_response(msg):
            assert idx > 0, "Function response cannot be the first message in trimmed history"
            assert _has_function_call(trimmed[idx - 1]), "Function response must be immediately preceded by function call"


def test_reset_command_clears_history(monkeypatch):
    """6.3) /reset clears the history."""
    input_prompts = [
        "How much did I spend in July 2026?",
        "/reset",
        "What about August?",
        "exit",
    ]
    prompt_iter = iter(input_prompts)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(prompt_iter))

    calls_received = []

    def mock_run_agent(question, history=None):
        calls_received.append({"question": question, "history": list(history) if history else []})
        dummy_content = types.Content(role="model", parts=[types.Part.from_text(text=f"Answer for {question}")])
        return AgentResult(
            answer=f"Answer for {question}",
            tool_calls=[],
            history=[dummy_content],
            status="ok",
        )

    monkeypatch.setattr(main_module, "run_agent", mock_run_agent)

    # Run main() interactive CLI
    main_module.main()

    # Verify that run_agent was called twice (for the 2 questions)
    assert len(calls_received) == 2
    assert calls_received[0]["question"] == "How much did I spend in July 2026?"
    assert calls_received[0]["history"] == []

    # After /reset, the second call must have received an empty history
    assert calls_received[1]["question"] == "What about August?"
    assert calls_received[1]["history"] == []


def test_agent_result_status_step_limit(monkeypatch):
    """6.4) AgentResult.status is 'step_limit' when the loop limit is reached."""
    class MockFunctionCall:
        name = "spending_by_category"
        args = {"category": "Groceries", "month": "2026-07"}

    class MockLoopResponse:
        candidates = [MagicMock(content=types.Content(
            role="model",
            parts=[types.Part.from_function_call(name="spending_by_category", args={"category": "Groceries", "month": "2026-07"})]
        ))]
        function_calls = [MockFunctionCall()]
        text = None

    mock_client = MagicMock()
    # Always return a function call so the loop never terminates naturally
    mock_client.models.generate_content.return_value = MockLoopResponse()
    monkeypatch.setattr("src.agent.genai.Client", lambda api_key=None: mock_client)

    result = run_agent("Loop indefinitely question", history=[])

    assert result.status == "step_limit"
    assert result.answer == "Sorry, that request needed too many steps. Please ask a simpler question."
    assert len(result.tool_calls) == 5  # MAX_AGENT_STEPS
