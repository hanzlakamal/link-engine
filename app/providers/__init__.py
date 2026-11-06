"""Data providers. Add a module + import it here to register a new source.

TODO(upgrade): free sources (SERP API + on-page crawl), Google Search Console (per client),
Semrush/Moz/Majestic, Common Crawl link graph for long-tail discovery.
"""
from app.providers import ahrefs, dataforseo  # noqa: F401
from app.providers.base import BacklinkProvider, ProviderError  # noqa: F401


def pick(names: list[str], usage_cb=None) -> BacklinkProvider | None:
    """First configured provider from the project's preference list."""
    from app.registry import providers

    for n in names:
        try:
            cls = providers.get(n)
        except KeyError:
            continue
        if cls.configured():
            return cls(usage_cb=usage_cb)
    return None
