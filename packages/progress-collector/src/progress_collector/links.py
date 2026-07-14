"""Small helpers for safe, consistently shaped outbound links."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

URL_RE = re.compile(r"https?://[^\s<>\]\[)]+")


def link(
    url: str | None, title: str | None = None, relation: str | None = None
) -> dict[str, str] | None:
    if not isinstance(url, str) or not url:
        return None
    value = {"url": url}
    if title:
        value["title"] = title
    if relation:
        value["relation"] = relation
    return value


def dedupe_links(links: Iterable[Mapping[str, str] | None]) -> tuple[dict[str, str], ...]:
    seen: set[str] = set()
    result: list[dict[str, str]] = []
    for item in links:
        if not item or not item.get("url") or item["url"] in seen:
            continue
        seen.add(item["url"])
        result.append(dict(item))
    return tuple(result)


def urls_in_text(text: str | None, relation: str) -> tuple[dict[str, str], ...]:
    if not isinstance(text, str):
        return ()
    return dedupe_links(link(url.rstrip(".,;:"), relation=relation) for url in URL_RE.findall(text))
