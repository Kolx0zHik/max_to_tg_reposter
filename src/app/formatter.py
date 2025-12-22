import html
from datetime import datetime
from typing import Optional

from pymax.types import Message


def escape(text: str) -> str:
    return html.escape(text or "", quote=False)


def format_message_text(message: Message, chat_title: str, author: Optional[str]) -> str:
    ts = datetime.fromtimestamp(message.time / 1000).strftime("%Y-%m-%d %H:%M:%S")
    author_line = f"Автор: {escape(author)}" if author else "Автор: неизвестно"
    header = "\n".join(
        [
            f"<b>{escape(chat_title)}</b>",
            f"<code>{ts}</code>",
            author_line,
        ]
    )
    body = escape(message.text or "")
    return f"{header}\n\n{body}" if body else header
