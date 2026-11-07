"""Provider interface. Every backlink/SEO data source implements this."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class CompetitorInfo:
    domain: str
    domain_rating: float | None = None
    traffic: int | None = None
    common_keywords: int | None = None


@dataclass
class DomainMetrics:
    domain: str
    domain_rating: float | None = None
    refdomains: int | None = None
    traffic: int | None = None
    keywords: int | None = None


@dataclass
class RawBacklink:
    source_url: str
    source_domain: str
    target_url: str = ""
    anchor: str = ""
    title: str = ""
    dofollow: bool = True
    domain_rating: float = 0
    traffic: int = 0
    page_type: str = ""
    is_spam: bool = False
    first_seen: str = ""
    extra: dict = field(default_factory=dict)


class ProviderError(RuntimeError):
    pass


class BacklinkProvider(ABC):
    name: str = "base"

    def __init__(self, usage_cb=None):
        # usage_cb(provider, endpoint, units) -> lets us track API spend per project
        self._usage_cb = usage_cb

    def _usage(self, endpoint: str, units: float) -> None:
        if self._usage_cb:
            self._usage_cb(self.name, endpoint, units)

    @classmethod
    @abstractmethod
    def configured(cls) -> bool:
        """True if credentials are present."""

    @abstractmethod
    def competitors(self, domain: str, country: str = "us", limit: int = 20) -> list[CompetitorInfo]: ...

    @abstractmethod
    def metrics(self, domain: str, country: str = "us") -> DomainMetrics: ...

    @abstractmethod
    def backlinks(self, domain: str, limit: int = 300, min_dr: float = 0,
                  include_traffic: bool = False) -> list[RawBacklink]: ...
