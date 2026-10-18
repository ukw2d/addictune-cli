"""Signed stream URLs carry the account's token, signature and address.

The first public bug report pasted one verbatim from an error toast, so every
URL that reaches a log or the screen goes through ``redact_url`` first.
"""

import unittest

from addictune_cli.src.logging_setup import redact_url

_SIGNED = (
    "https://content.audioaddict.com/prd/7/2/track.mp3?purpose=playback"
    "&audio_token=37f370968f&member_id=16947484&network=di&ip=2804%3A14d%3A1"
    "&ip_type=6&masked_ipv6=2804%3A14d%3A%3A%2F64&exp=2026-10-18T13%3A34%3A32Z"
    "&auth=26d81387bf&listen_key=fceffbccd2"
)


class RedactUrlTests(unittest.TestCase):
    def test_masks_every_credential_and_address_param(self) -> None:
        redacted = redact_url(_SIGNED)

        for secret in ("37f370968f", "16947484", "2804", "26d81387bf", "fceffbccd2"):
            self.assertNotIn(secret, redacted)
        self.assertIn("audio_token=***", redacted)

    def test_keeps_the_parts_a_bug_report_needs(self) -> None:
        redacted = redact_url(_SIGNED)

        self.assertTrue(
            redacted.startswith("https://content.audioaddict.com/prd/7/2/track.mp3?")
        )
        for kept in ("purpose=playback", "network=di", "ip_type=6", "exp=2026-10-18"):
            self.assertIn(kept, redacted)
