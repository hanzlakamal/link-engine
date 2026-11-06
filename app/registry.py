"""Plugin registries — the main "room for upgrades" mechanism.

To add a new data source, channel, strategy or playbook: create a module, subclass the
relevant base, decorate with @registry.<kind>.register("name"), and import it in that
package's __init__. Nothing else in the app needs to change.
"""
from __future__ import annotations

from typing import Callable, Generic, TypeVar

T = TypeVar("T")


class Registry(Generic[T]):
    def __init__(self, kind: str):
        self.kind = kind
        self._items: dict[str, type[T]] = {}

    def register(self, name: str) -> Callable[[type[T]], type[T]]:
        def deco(cls: type[T]) -> type[T]:
            if name in self._items:
                raise ValueError(f"{self.kind} '{name}' already registered")
            cls.name = name  # type: ignore[attr-defined]
            self._items[name] = cls
            return cls

        return deco

    def get(self, name: str) -> type[T]:
        try:
            return self._items[name]
        except KeyError:
            raise KeyError(f"Unknown {self.kind} '{name}'. Known: {sorted(self._items)}")

    def names(self) -> list[str]:
        return sorted(self._items)

    def items(self):
        return sorted(self._items.items())


providers: Registry = Registry("provider")
strategies: Registry = Registry("strategy")
channels: Registry = Registry("channel")
playbooks: Registry = Registry("playbook")


def load_plugins() -> None:
    """Import plugin packages so their @register decorators run."""
    import app.channels  # noqa: F401
    import app.playbooks  # noqa: F401
    import app.providers  # noqa: F401
    import app.strategies  # noqa: F401
