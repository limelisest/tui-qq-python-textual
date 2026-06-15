"""App-wide CSS string for the TUI.

Kept as a Python string constant instead of a .tcss file so that PyInstaller
single-file builds do not need extra ``datas`` entries and the layout stays
self-contained.
"""

APP_CSS = """
Screen {
    layout: vertical;
}

#top_bar {
    height: 1;
    background: $panel;
    color: $foreground;
}

#sidebar_toggle_btn,
#header_menu_btn {
    width: 3;
    min-width: 3;
    height: 1;
    min-height: 1;
    margin: 0 0;
    padding: 0 0;
    border: none;
    line-pad: 1;
    background: $panel;
    color: $foreground;
    text-style: bold;
    content-align: center middle;
}

#sidebar_toggle_btn:hover,
#header_menu_btn:hover {
    background: $boost;
}

#app_title {
    width: 1fr;
    height: 1;
    padding: 0 1;
    background: $panel;
    color: $foreground;
    text-style: bold;
    content-align: center middle;
    text-wrap: nowrap;
    text-overflow: ellipsis;
}

#top_bar_spacer {
    width: 6;
    min-width: 6;
    height: 1;
    background: $panel;
}

#body {
    height: 1fr;
}

#sidebar {
    width: 34;
    min-width: 24;
    border-right: solid $primary;
    background: $surface;
}

#search {
    height: 3;
    margin: 0 1 1 1;
}

#chat_list {
    height: 1fr;
}

#chat_list > ListItem.-highlight {
    color: $block-cursor-foreground;
    background: $block-cursor-background;
    text-style: $block-cursor-text-style;
}

.chat_list_item {
    height: 3;
}

.chat_item {
    height: 3;
}

.chat_name {
    height: 1;
    padding: 0 0;
}

.chat_preview {
    height: 1;
    padding: 0 0;
    color: $text-muted;
}

.chat_gap {
    height: 1;
}

.chat_separator_item {
    height: 1;
}

.chat_separator {
    height: 1;
    padding: 0 1;
    color: $text-muted;
}

#main {
    width: 1fr;
}

#chat_area {
    height: 1fr;
}

#msg_log {
    height: 1fr;
    padding: 0 1;
}

.message_log_line {
    height: auto;
    padding: 0 0;
}

#reply_info {
    height: 1;
    padding: 0 1;
    color: $warning;
}

#input_row {
    height: 3;
    margin: 1 0 1 0;
}

#msg_input {
    width: 1fr;
    height: 3;
}

#scroll_bottom_btn {
    width: 3;
    min-width: 3;
    height: 3;
    display: none;
}

#toast_row {
    height: 0;
}

#toast_row.visible {
    height: 3;
}

#toast_spacer {
    width: 1fr;
}

#toast {
    width: 38;
    height: 3;
    margin: 0 1 0 0;
    padding: 0 1;
    border: solid $accent;
    background: $boost;
    color: $text;
}
"""
