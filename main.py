#!/usr/bin/env python3
"""QQ Chat TUI --- Textual-based QQ chat client using NapCat backend."""

from ui import QQChatApp


def main():
    app = QQChatApp()
    app.run()


if __name__ == "__main__":
    main()
