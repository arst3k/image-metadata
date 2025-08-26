"""
Entry point for the image-metadata CLI tool.
Delegates to src.cli.main().
"""

from src.cli import main as cli_main


def main() -> None:
    cli_main()


if __name__ == "__main__":
    main()
