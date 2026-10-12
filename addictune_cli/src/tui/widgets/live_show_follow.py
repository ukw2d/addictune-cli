from textual.widgets import Label

from ..presentation import LIVE_SHOW_FOLLOW_LABELS
from ..types import ContentType
from ..utils import replace_modifier_class


def is_live_show_airing(show_id: int | None, content_type: ContentType) -> bool:
    """Whether a live show is currently airing -- the shared gate behind the
    bar marker (below) and the expanded player's channel label/chip.
    """
    return show_id is not None and content_type == ContentType.LIVE


def apply_live_show_follow_marker(
    label: Label,
    *,
    show_id: int | None,
    show_name: str,
    followed: bool | None,
    content_type: ContentType,
) -> None:
    """Render the followed/not-followed marker for the airing live show.

    Live-scoped by design: on-demand mixshow/playlist/track
    playback never shows this, even though an on-demand episode also has a
    parent show. ``followed`` is ``None`` both while not logged in (never
    fetched) and during the brief window before a fresh fetch resolves --
    both render as no marker, since there is nothing true to assert yet.
    """
    css_classes = tuple(spec.css_class for spec in LIVE_SHOW_FOLLOW_LABELS.values())
    spec = (
        LIVE_SHOW_FOLLOW_LABELS.get(followed)
        if is_live_show_airing(show_id, content_type)
        else None
    )
    if spec is None:
        replace_modifier_class(label, css_classes, None)
        label.update("")
        label.tooltip = None
        return
    label.update(spec.label)
    replace_modifier_class(label, css_classes, spec.css_class)
    label.tooltip = show_name or None
