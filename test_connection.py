# Import the Google GenAI SDK to communicate with Gemini models.
from google import genai

# Import the model name and API key directly from the project's configuration file.
from src.config import MODEL, GEMINI_API_KEY

# Create an authenticated Gemini client using the API key loaded from .env.
client = genai.Client(api_key=GEMINI_API_KEY)

# Send a prompt to the model requesting it to reply with the word OK.
response = client.models.generate_content(
    model=MODEL,
    contents="Reply with the word OK",
)

# Output the text response received from the Gemini model to the terminal.
print(response.text)
