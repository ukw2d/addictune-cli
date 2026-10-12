from textual.widgets import Label

from ..presentation import LIVE_SHOW_BADGE_LABELS
from ..types import MediaStatusState
from ..utils import replace_modifier_class


def apply_live_show_badge(label: Label, value: MediaStatusState | None) -> None:
    css_classes = tuple(spec.css_class for spec in LIVE_SHOW_BADGE_LABELS.values())
    badge_spec = LIVE_SHOW_BADGE_LABELS.get(value.status) if value is not None else None
    label.display = badge_spec is not None
    if badge_spec is None:
        replace_modifier_class(label, css_classes, None)
        label.update("")
        label.tooltip = None
        return

    label.update(badge_spec.label)
    replace_modifier_class(label, css_classes, badge_spec.css_class)
    label.tooltip = value.episode.name if value.episode is not None else None
