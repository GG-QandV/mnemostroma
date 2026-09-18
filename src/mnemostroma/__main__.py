# SPDX-License-Identifier: FSL-1.1-MIT
"""Mnemostroma — local cognitive memory layer for AI agents.

Main entry point. Logic extracted to cli/commands.py for modularity.
"""
import sys

from mnemostroma.cli.commands import build_cli, dispatch

_HELP_FLAGS = ("-h", "--help", "help")


def main():
    # The parser is built with add_help=False and owns no options, so argparse
    # would reject `-h`/`--help` as unrecognised and exit 2. Treat them as the
    # help command instead — it is the first thing a new user types.
    argv = sys.argv[1:]
    if argv and argv[0] in _HELP_FLAGS:
        argv = ["help"]
    parser = build_cli()
    args = parser.parse_args(argv)
    dispatch(args)

# Alias for console_scripts entry point in pyproject.toml
cli = main

if __name__ == "__main__":
    main()
