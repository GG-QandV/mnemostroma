# SPDX-License-Identifier: FSL-1.1-MIT
"""Mnemostroma — local cognitive memory layer for AI agents.

Main entry point. Logic extracted to cli/commands.py for modularity.
"""
from mnemostroma.cli.commands import build_cli, dispatch

def main():
    parser = build_cli()
    args = parser.parse_args()
    dispatch(args)

# Alias for console_scripts entry point in pyproject.toml
cli = main

if __name__ == "__main__":
    main()
