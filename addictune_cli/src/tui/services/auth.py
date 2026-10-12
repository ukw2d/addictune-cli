"""Auth-session recovery.

Every caller that hits an authenticated endpoint (services/channels.py,
services/follow.py, services/votes.py, widgets/playback_bar.py,
widgets/media_list.py) funnels through one of these two entry points to get a
valid session before proceeding: log in again from the stored credentials,
else prompt.
"""

import logging
from typing import TYPE_CHECKING

from ...auth import sign_in
from ..presentation import AUTH_ERROR_GENERIC

if TYPE_CHECKING:
    from ..app import AddictuneApp

_log = logging.getLogger("addictune_cli.auth")


class AuthRecoveryService:
    def __init__(self, app: "AddictuneApp") -> None:
        self.app = app

    async def ensure_authenticated_session(self, network: str) -> bool:
        """Ensure a session for *network*, prompting only after silent login fails."""
        app = self.app
        if app.user_id is not None and app.client.has_session(network):
            return True
        return await self.recover_auth(network)

    async def recover_auth(self, network: str | None = None) -> bool:
        """Replace an expired or missing session; True once one is ready to use.

        Prompts only when there is nothing to sign in with or the server
        rejected it; a server or connection failure just reports and returns
        False, keeping the stored credentials.
        """
        app = self.app
        try:
            user_id = await sign_in(app.client, network or app.network)
        except Exception as exc:
            _log.warning("sign-in failed: %r", exc)
            app.notify(AUTH_ERROR_GENERIC, severity="error")
            return False
        if user_id is None:
            app._prompt_login()
            return False
        app.user_id = user_id
        return True
