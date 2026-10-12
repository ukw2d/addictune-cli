from textual.binding import Binding
from textual.widgets import Footer
from textual.widgets._footer import FooterKey


class AppFooter(Footer):
    """Keep footer keys in app binding order after Textual renders them."""

    async def recompose(self) -> None:
        await super().recompose()
        self._apply_app_footer_overrides()
        self._sort_footer_keys()

    def _apply_app_footer_overrides(self) -> None:
        visible_for_action = getattr(self.app, "footer_action_visible", None)
        description_for_action = getattr(self.app, "footer_description_for_action", None)
        for child in list(self.walk_children(FooterKey)):
            disabled = bool(getattr(child, "_disabled", False))
            if (
                visible_for_action is not None
                and not visible_for_action(child.action, disabled)
            ):
                child.remove()
                continue
            if description_for_action is None:
                continue
            description = description_for_action(child.action, child.description)
            if description != child.description:
                child.description = description
                child.refresh()

    def _sort_footer_keys(self) -> None:
        self.sort_children(key=lambda child: self._binding_order(child))

    def _binding_order(self, child) -> tuple[int, str]:
        action = child.action if isinstance(child, FooterKey) else ""
        app_bindings = getattr(self.app, "BINDINGS", ())
        for index, binding in enumerate(app_bindings):
            if isinstance(binding, Binding) and binding.action == action:
                return index, action
        return len(app_bindings), action
