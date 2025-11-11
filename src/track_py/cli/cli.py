from prompt_toolkit.completion import WordCompleter
from src.track_py.utils.logger import logger
from prompt_toolkit.shortcuts import PromptSession
from prompt_toolkit.patch_stdout import patch_stdout
from ..cli import command


commands = [
    # "start",
    # "help",
    "today",
    "week",
    "month",
    "gas",
    "food",
    "dating",
    "other",
    "investment",
    "freelance",
    "salary",
    "income",
    "sort",
    "ai",
    # "stats",
    "categories",
    "sync_config",
    "keywords",
    "assets",
    "migrate_assets",
    "price",
    "profit",
]
completer = WordCompleter(commands, ignore_case=True)


async def interactive_shell():
    """
    A coroutine that runs an interactive prompt loop.
    """
    session = PromptSession()
    while True:
        try:
            # Use patch_stdout to ensure other async tasks can print above the prompt
            with patch_stdout():
                result = await session.prompt_async(
                    "track-py> ", completer=completer, complete_while_typing=True
                )

            cmd = str(result).lower()
            if cmd in ("quit", "exit"):
                print("Exiting interactive shell.")
                break

            # Handle the command
            response = await command.handle_command(cmd)
            logger.info(f"Executed command: {cmd} with response:\n\n{response}")

        except (EOFError, KeyboardInterrupt):
            # Handle Ctrl+D or Ctrl+C to exit gracefully
            print("Exiting interactive shell.")
            break
