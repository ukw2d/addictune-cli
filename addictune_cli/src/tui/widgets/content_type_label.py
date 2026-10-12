from textual.widgets import Label

from ..presentation import CONTENT_TYPE_LABELS
from ..types import ContentType
from ..utils import replace_modifier_class


def apply_content_type_label(label: Label, value: ContentType) -> None:
    spec = CONTENT_TYPE_LABELS[value]
    label.update(spec.label)
    replace_modifier_class(
        label,
        (spec.css_class for spec in CONTENT_TYPE_LABELS.values()),
        spec.css_class,
    )
