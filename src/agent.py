"""Autonomous agent loop using the Google GenAI SDK with manual tool calling, permissions, and logging."""

import json
from google import genai
from google.genai import types

from src.config import MODEL, MAX_AGENT_STEPS, GEMINI_API_KEY
from src.logger import log_event
from src.permissions import check_permission
from src.prompts import build_system_prompt
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

# Bundle all allowed function declarations into a single Gemini Tool
agent_tool = types.Tool(function_declarations=function_declarations)


def run_agent(question: str) -> str:
    """Execute the agent loop to answer a user question using available tools, permission checks, and logging."""
    # 2.1) question: log the user's question at the start of run_agent
    log_event("question", {"question": question})

    try:
        # Initialize authenticated Gemini client
        client = genai.Client(api_key=GEMINI_API_KEY)

        # Build dynamic system prompt with the current date
        system_prompt = build_system_prompt()

        # Configure generation settings including tools and current system instructions
        tool_config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            tools=[agent_tool],
        )

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
                answer = response.text or ""
                # 2.5) final_answer: log the answer text
                log_event("final_answer", {"answer": answer})
                return answer

            # Collect function response parts to return in a single user message
            response_parts = []
            for call in response.function_calls:
                tool_name = call.name
                tool_args = call.args or {}

                # Print tool invocation details to the terminal (never print API keys)
                print(f"[Tool Call] {tool_name}({tool_args})")

                # 2.2) tool_call: log tool name and arguments before execution
                log_event("tool_call", {"tool_name": tool_name, "arguments": tool_args})

                # Check permissions before running any tool
                if not check_permission(tool_name):
                    print(f"[Permission Denied] Tool '{tool_name}' execution is blocked by permissions.")
                    # 2.4) permission_denied: log tool name whenever check_permission returns False
                    log_event("permission_denied", {"tool_name": tool_name})
                    tool_result = {"error": "This action is not permitted."}
                else:
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
                        err_msg = str(e)
                        # 2.6) error: log exception with a short message
                        log_event("error", {"error": err_msg, "tool_name": tool_name})
                        tool_result = {"error": f"Error running '{tool_name}': {err_msg}"}

                # 2.3) tool_result: log tool name and result, truncating longer than 1000 characters
                res_to_log = tool_result
                if isinstance(res_to_log, (dict, list)):
                    s = json.dumps(res_to_log)
                    if len(s) > 1000:
                        res_to_log = s[:1000]
                elif isinstance(res_to_log, str) and len(res_to_log) > 1000:
                    res_to_log = res_to_log[:1000]

                log_event("tool_result", {"tool_name": tool_name, "result": res_to_log})

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

        # 2.7) step_limit_reached: log when MAX_AGENT_STEPS is hit
        log_event("step_limit_reached", {"max_steps": MAX_AGENT_STEPS})
        fallback = "Sorry, that request needed too many steps. Please ask a simpler question."
        log_event("final_answer", {"answer": fallback})
        return fallback

    except Exception as e:
        err_msg = str(e)
        # 2.6) error: log any exception with a short message
        log_event("error", {"error": err_msg})
        return f"An error occurred: {err_msg}"
