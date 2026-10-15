"""Interactive terminal chat entry point for the finance assistant agent."""

from src.agent import run_agent


def main():
    """Run an interactive CLI loop prompting the user for questions."""
    print("Personal Finance Assistant CLI (type 'exit' to quit)")
    print("-" * 60)

    while True:
        try:
            user_input = input("\nYou: ").strip()
            if not user_input:
                continue
            if user_input.lower() in ("exit", "quit"):
                print("Goodbye!")
                break

            answer = run_agent(user_input)
            print(f"\nAssistant: {answer}")
        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye!")
            break


if __name__ == "__main__":
    main()
