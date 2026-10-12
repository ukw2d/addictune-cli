"""Type-narrowing mixin so project nodes see ``self.app`` as ``AddictuneApp``.

Textual's ``DOMNode.app`` is typed as the base ``App``, so every widget/screen
that reaches an app-level singleton (``client``, ``network``,
``playing_episode_id``, ``play_episode``, ...) would otherwise need a per-site
attr-defined suppression comment. Mixing in :class:`AppNode` narrows the return
type in exactly one place.

This is purely a typing construct: the ``app`` override lives under
``TYPE_CHECKING`` and contributes nothing at runtime, so the real
``DOMNode.app`` property still services the attribute. List ``AppNode`` first in
the bases so it wins the MRO lookup for type checkers.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .app import AddictuneApp


class AppNode:
    if TYPE_CHECKING:

        @property
        def app(self) -> "AddictuneApp": ...
