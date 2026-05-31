"""Send push notifications to your phone via ntfy."""

from __future__ import annotations

import requests

from .config import NtfyConfig

_TIMEOUT = 10


class NotifyError(Exception):
    pass


def send(
    ntfy: NtfyConfig,
    *,
    title: str,
    message: str,
    tags: str | None = None,
    priority: str | None = None,
) -> None:
    """Publish a notification to the configured ntfy topic.

    ntfy is a simple HTTP pub-sub: the body is the message, and metadata travels
    in headers. The phone subscribes to `<server>/<topic>` in the ntfy app.
    """
    url = f"{ntfy.server}/{ntfy.topic}"
    headers = {"Title": title, "Priority": priority or ntfy.priority}
    if tags:
        headers["Tags"] = tags
    try:
        resp = requests.post(
            url, data=message.encode("utf-8"), headers=headers, timeout=_TIMEOUT
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise NotifyError(f"Failed to send ntfy notification: {exc}") from exc
