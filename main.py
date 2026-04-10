#!/usr/bin/env python3
"""MyCLI - Copilot 风格的终端 AI 助手"""

from cli.app import ChatApp


def main():
    app = ChatApp()
    app.run()


if __name__ == "__main__":
    main()
