"""Readable terminal presentation; persisted evidence stays independent of display."""

import json
import os
import shutil
import textwrap


class Terminal:
    def __init__(self, stream):
        self.stream = stream
        self.color = (getattr(stream, "isatty", lambda: False)()
                      and "NO_COLOR" not in os.environ and os.environ.get("TERM") != "dumb")
        self.width = min(100, max(40, shutil.get_terminal_size((100, 24)).columns - 2))

    def write(self, text="", style=None):
        codes = {"heading": "1;36", "muted": "2", "label": "1"}
        if self.color and style:
            text = f"\033[{codes[style]}m{text}\033[0m"
        print(text, file=self.stream, flush=True)

    def prose(self, text, style=None, prefix=""):
        for line in text.splitlines():
            if not line.strip():
                self.write()
                continue
            self.write(textwrap.fill(line, width=self.width, initial_indent=prefix,
                                     subsequent_indent=" " * len(prefix),
                                     break_long_words=False, break_on_hyphens=False), style)

    def debug(self, text):
        self.write(f"[Debug] {text}", "muted")

    def json(self, value):
        self.write(json.dumps(value, indent=2, ensure_ascii=False), "muted")


def readable_tool_result(result):
    """Expand JSON encoded inside SDK text blocks for display only."""
    displayed = dict(result)
    displayed["content"] = []
    for block in result.get("content", []):
        if isinstance(block, dict) and isinstance(block.get("text"), str):
            try:
                decoded = json.loads(block["text"])
            except ValueError:
                pass
            else:
                if isinstance(decoded, (dict, list)):
                    block = {**block, "json": decoded}
                    del block["text"]
        displayed["content"].append(block)
    return displayed
