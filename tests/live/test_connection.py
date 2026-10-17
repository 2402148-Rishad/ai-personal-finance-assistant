"""Live integration test for Gemini API connectivity."""

from google import genai
import pytest

from src.config import MODEL, get_api_key


@pytest.mark.live
def test_connection():
    """Verify live connectivity with Gemini API."""
    client = genai.Client(api_key=get_api_key())
    response = client.models.generate_content(
        model=MODEL,
        contents="Reply with the word OK",
    )
    assert response.text is not None
    print(response.text)
