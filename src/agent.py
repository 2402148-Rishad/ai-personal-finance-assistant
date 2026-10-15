"""Autonomous agent loop using the Google GenAI SDK with manual tool calling."""

import json
from google import genai
from google.genai import types

from src.config import MODEL, MAX_AGENT_STEPS, GEMINI_API_KEY
from src.tools import TOOL_SCHEMAS, TOOLS_BY_NAME

# Convert tool dictionary schemas into Gemini FunctionDeclarations
function_declarations = []
for schema in TOOL_SCHEMAS:
    # Map input_schema to parameters if present, and retain only supported fields
    parameters = schema.get("parameters") or schema.get("input_schema")
    function_declarations.append(
        types.FunctionDeclaration(
            name=schema["name"],
            description=schema.get("description", ""),
            parameters=parameters,
        )
    )

# Bundle all function declarations into a single Gemini Tool
agent_tool = types.Tool(function_declarations=function_declarations)

# System instruction guiding the model's behavior
SYSTEM_PROMPT = "You are a personal finance assistant. Use tools for every number. Never invent amounts."

# Configure generation settings including tools and system instructions
tool_config = types.GenerateContentConfig(
    system_instruction=SYSTEM_PROMPT,
    tools=[agent_tool],
)


def run_agent(question: str) -> str:
    """Execute the agent loop to answer a user question using available tools."""
    # Initialize authenticated Gemini client
    client = genai.Client(api_key=GEMINI_API_KEY)

    # Initialize message history with the user's initial question
    history = [
        types.Content(
            role="user",
            parts=[types.Part.from_text(text=question)],
        )
    ]

    # Run the loop up to MAX_AGENT_STEPS turns
    for step in range(MAX_AGENT_STEPS):
        # Call the Gemini model with conversation history and tool configuration
        response = client.models.generate_content(
            model=MODEL,
            contents=history,
            config=tool_config,
        )

        # Append model response to conversation history as-is
        if response.candidates and response.candidates[0].content:
            history.append(response.candidates[0].content)

        # If model did not request any function calls, return final text
        if not response.function_calls:
            return response.text or ""

        # Collect function response parts to return in a single user message
        response_parts = []
        for call in response.function_calls:
            tool_name = call.name
            tool_args = call.args or {}

            # Print tool invocation details to the terminal (never print API keys)
            print(f"[Tool Call] {tool_name}({tool_args})")

            # Look up and execute the requested tool with error handling
            try:
                if tool_name not in TOOLS_BY_NAME:
                    tool_result = {"error": f"Tool '{tool_name}' not found."}
                else:
                    raw_result = TOOLS_BY_NAME[tool_name](**tool_args)
                    parsed_result = json.loads(raw_result)
                    # Ensure the response is wrapped as a dictionary for Gemini
                    if isinstance(parsed_result, dict):
                        tool_result = parsed_result
                    else:
                        tool_result = {"result": parsed_result}
            except Exception as e:
                # Catch any unexpected tool failure and report as an error dictionary
                tool_result = {"error": f"Error running '{tool_name}': {str(e)}"}

            # Build function response part
            response_parts.append(
                types.Part.from_function_response(
                    name=tool_name,
                    response=tool_result,
                )
            )

        # Send all tool results back to the model as a single user message
        history.append(
            types.Content(
                role="user",
                parts=response_parts,
            )
        )

    # Return fallback message if loop limit was reached without completion
    return "Sorry, that request needed too many steps. Please ask a simpler question."
