from __future__ import annotations

from typing import Any

from ddgs import DDGS
from ddgs.exceptions import DDGSException


def search_place(name: str, city: str = "Chisinau", max_results: int = 5) -> list[dict[str, Any]]:
    queries = [
        f'"{name}" {city} menu',
        f'"{name}" {city} restaurant',
        f'"{name}" {city} food',
        f'{name} {city}',
        f'"{name}" {city} instagram',
    ]

    seen = set()
    results: list[dict[str, Any]] = []

    with DDGS() as ddgs:
        for query in queries:
            try:
                items = ddgs.text(query, max_results=max_results)
            except DDGSException:
                # No results for this query, or a transient backend/rate-limit error.
                continue
            for item in items:
                url = item.get("href")
                if not url or url in seen:
                    continue
                seen.add(url)
                results.append({
                    "query": query,
                    "title": item.get("title"),
                    "url": url,
                    "snippet": item.get("body"),
                })

    return results[:max_results]


if __name__ == "__main__":
    for row in search_place("Draft Arena"):
        print(row)
