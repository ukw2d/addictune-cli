from dataclasses import dataclass

from ..audio.state import State
from .types import ContentType, MediaStatus


@dataclass(frozen=True)
class CssLabel:
    label: str
    css_class: str


@dataclass(frozen=True)
class StatusLabel:
    label: str
    modifier: str


APP_TITLE = "AddictuneApp"

AUTH_TITLE = "Sign in"
AUTH_BRAND = "♫  AddicTune"
AUTH_TAGLINE = "CLI client for AudioAddict radio stations"
AUTH_EMAIL_LABEL = "Email"
AUTH_PASSWORD_LABEL = "Password"
AUTH_EMAIL_PLACEHOLDER = "you@example.com"
AUTH_PASSWORD_PLACEHOLDER = "Password"
AUTH_LOGIN_LABEL = "Sign in"
AUTH_HINT = "Enter to submit · Esc to cancel"
AUTH_ERROR_INVALID = "⚠  Invalid email or password. Please try again."
AUTH_ERROR_GENERIC = "⚠  Couldn't sign in. Check your connection and try again."
AUTH_EMAIL_REQUIRED = "⚠  Please enter your email."
AUTH_PASSWORD_REQUIRED = "⚠  Please enter your password."

ACCOUNT_TIERS = {True: "Premium", False: "Free"}
AUTH_SIGNED_OUT = "Signed out."
AUTH_SIGNED_OUT_KEPT = (
    "Signed out. The saved login could not be removed; delete it from your system's credential store."
)
SIGN_OUT_TITLE = "Sign out of {station}?"
SIGN_OUT_BODY = (
    "Your saved login is removed from this computer and playback stops."
)
CONFIRM_CANCEL = "Cancel"
ACCOUNT_FREE_HINT = "Streams need a Premium subscription; see the station's website."

TAB_CHANNELS = "Channels"
TAB_MIXSHOWS = "Mixshows"
TAB_PLAYLISTS = "Playlists"
TAB_TRACKS = "Tracks"
TRACKS_HISTORY_PLACEHOLDER = "Listening history is coming soon"
TRACKS_EMPTY = "No liked tracks yet"

BINDING_SETTINGS = "Settings"
BINDING_INFO_PANEL = "Info"
BINDING_EXPANDED_PLAYER = "Expand"
BINDING_PLAY_PAUSE = "Play"
BINDING_STOP = "Stop"
BINDING_MUTE = "Mute"
BINDING_VOLUME_UP = "Vol +"
BINDING_VOLUME_DOWN = "Vol -"
BINDING_SEEK_LEFT = "←"
BINDING_SEEK_RIGHT = "→"
BINDING_PREVIOUS_TRACK = "Prev"
BINDING_NEXT_TRACK = "Next"
BINDING_PLAY = "Play"
BINDING_BACK = "Back"

SYSTEM_TOGGLE_DARK = "Toggle dark mode"
SYSTEM_SIGN_OUT = "Sign out"
SYSTEM_TOGGLE_DARK_DESCRIPTION = "Switch between light and dark theme"

NO_TRACKS_AVAILABLE = "No tracks available"
PLAYLIST_SKIP_UNAVAILABLE = "Finish this playlist set before loading another."
PLAYLIST_NO_NEW_TRACKS = "No new playlist tracks are available yet."
PLAYBACK_FAILED = "Playback failed: {detail}"
PLAYBACK_NEEDS_PREMIUM = "This stream needs a Premium subscription (signed in as Free)."
PLAYBACK_RECONNECTING = "Stream dropped — reconnecting…"
# Failures are the one notification worth reading in full before it fades.
PLAYBACK_ERROR_TIMEOUT = 10.0

MEDIA_METADATA_EPISODES = "Episodes"
MEDIA_METADATA_SCHEDULE = "Schedule"
MEDIA_LIVE_STATUS = StatusLabel("[$success]◉ LIVE NOW[/]", "live")
MEDIA_UPCOMING_STATUS = StatusLabel("[$warning]◷ UPCOMING{suffix}[/]", "upcoming")
MEDIA_NOW_PLAYING_STATUS = StatusLabel("▶ NOW PLAYING", "playing")

VOLUME_ICON = "♪"
VOLUME_MUTED = f"{VOLUME_ICON} --"
PLAYBACK_SEPARATOR = "·"
INITIAL_TIME_LABEL = "00:00"
# Shown in place of the last ICY-derived track/title once a channel stops,
# since a stopped channel isn't "now playing" anything.
PLAYBACK_STOPPED_PLACEHOLDER = "--//--"

# ── Animation timings (seconds) ───────────────────────────────────────────────
# Shared across panels so timings stay consistent and drift-free.
ANIMATION_FAST = 0.2   # search bar, expanded player
ANIMATION_SLOW = 0.3   # media info panel
IMAGE_DEBOUNCE = 0.25  # coalesce rapid track-image changes

PLAYBACK_STATE_ICONS = {
    State.STOPPED: "■",
    State.LOADING: "◌",
    State.PLAYING: "▶",
    State.PAUSED: "‖",
}

CONTENT_TYPE_LABELS = {
    ContentType.LIVE: CssLabel("LIVE", "live"),
    ContentType.MIXSHOW: CssLabel("MIX", "mix"),
    ContentType.PLAYLIST: CssLabel("PL", "playlist"),
    ContentType.TRACK: CssLabel("TRK", "trk"),
}

LIVE_SHOW_BADGE_LABELS = {
    MediaStatus.LIVE_NOW: CssLabel("LIVE NOW", "live-show-badge--live"),
    MediaStatus.UPCOMING: CssLabel("UPCOMING", "live-show-badge--upcoming"),
}

# Keyed by PlaybackBar.live_show_followed (True/False only -- None means no
# marker at all, see apply_live_show_follow_marker).
LIVE_SHOW_FOLLOW_LABELS = {
    True: CssLabel("♥", "live-show-follow--followed"),
    False: CssLabel("♡", "live-show-follow--unfollowed"),
}
