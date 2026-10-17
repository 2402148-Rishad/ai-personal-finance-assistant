from pathlib import Path
from unittest.mock import MagicMock, patch

from streamlit.testing.v1 import AppTest

APP_PATH = (Path(__file__).resolve().parent.parent / "app.py").resolve()


def test_app_ui():
    with patch("src.agent.run_agent", return_value=MagicMock()):
        at = AppTest.from_file(str(APP_PATH), default_timeout=10).run()

        # Assert no markdown element contains font-family, /*, or <style
        for m in at.markdown:
            assert "font-family" not in m.value
            assert "/*" not in m.value
            assert "<style" not in m.value

        # With no messages, the placeholder phrase appears in zero markdown elements
        # and exactly once as the text input's placeholder
        placeholder = "Ask about spending, bills, or savings."
        assert sum(placeholder in m.value for m in at.markdown) == 0

        placeholders = [t.placeholder for t in at.text_input]
        assert placeholders.count(placeholder) == 1


def test_app_ui_escaped_dollars():
    stub_result = MagicMock()
    stub_result.status = "success"
    stub_result.answer = "You spent $407.31 and $102.65 on groceries and bills."
    stub_result.tool_calls = []
    stub_result.history = []

    with patch("src.agent.run_agent", return_value=stub_result):
        at = AppTest.from_file(str(APP_PATH), default_timeout=10).run()
        at.text_input[0].input("What did I spend?")
        at.form_submit_button[0].click().run()

        markdown_values = [m.value for m in at.markdown]
        assert any(r"\$407.31" in val and r"\$102.65" in val for val in markdown_values)

