from ..cli import cli
import asyncio


if __name__ == "__main__":
    asyncio.run(cli.interactive_shell())
