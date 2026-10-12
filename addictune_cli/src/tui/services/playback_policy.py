from dataclasses import dataclass

from ...audio.state import State
from ..types import ContentType

MAX_RETRY_ATTEMPTS = 12
RETRY_DELAY = 0.5
MAX_RETRY_DELAY = 15.0


def retry_delay(attempt: int) -> float:
    """Seconds to wait before reconnect *attempt* (1-based).

    Doubles up to MAX_RETRY_DELAY: the first attempts stay quick enough to be
    inaudible for a momentary blip, while the tail stretches the budget past
    two minutes. A flat delay spent all 12 attempts within ~6s, giving up while
    the network was still coming back.
    """
    return min(RETRY_DELAY * 2 ** (attempt - 1), MAX_RETRY_DELAY)


@dataclass(frozen=True)
class BackendPlay:
    generation: int
    url: str
    content_type: ContentType


@dataclass(frozen=True)
class BackendStop:
    generation: int
    post_stopped: bool


@dataclass(frozen=True)
class ScheduleRetry:
    generation: int
    delay: float
    url: str
    attempt: int
    max_attempts: int


BackendCommand = BackendPlay | BackendStop | ScheduleRetry


class PlaybackController:
    """Playback state machine and live-stream retry policy.

    The generation here numbers *user-level* plays and retries; the audio
    client has its own counter for child events. They are not compared.
    """

    def __init__(self) -> None:
        self._generation = 0
        self._url: str | None = None
        self._state = State.STOPPED
        self._now_playing = ""
        self._content_type = ContentType.LIVE
        self._retry_attempts = 0

    @property
    def current_url(self) -> str | None:
        return self._url

    @property
    def state(self) -> State:
        return self._state

    @property
    def now_playing(self) -> str:
        return self._now_playing

    def is_current(self, generation: int) -> bool:
        return generation == self._generation

    def play(self, url: str, title: str, content_type: ContentType) -> BackendPlay:
        self._generation += 1
        self._url = url
        self._content_type = content_type
        self._retry_attempts = 0
        self._now_playing = title
        self._state = State.LOADING
        return BackendPlay(self._generation, url, content_type)

    def stop(self, *, post_stopped: bool) -> BackendStop:
        self._generation += 1
        self._retry_attempts = 0
        self._state = State.STOPPED
        # Preserve last title so OS media sessions remain identifiable/routable
        # while playback is resumable.
        return BackendStop(self._generation, post_stopped)

    def pause(self) -> None:
        self._state = State.PAUSED

    def resume(self) -> None:
        self._state = State.PLAYING

    def set_icy_title(self, title: str) -> None:
        self._now_playing = title

    def playing(self) -> None:
        """The backend confirmed audio is flowing."""
        if self._state != State.STOPPED:
            self._retry_attempts = 0
            self._state = State.PLAYING

    def backend_exited(self, *, fatal: bool = False) -> BackendCommand | None:
        """Retry a dropped live stream, or stop when there is nothing to retry.

        *fatal* marks a failure that reproduces identically on every attempt --
        a misconfigured audio device, say -- where retrying only delays the
        error the user needs to see.
        """
        if self._state == State.STOPPED:
            return None
        if fatal or self._content_type != ContentType.LIVE or not self._url:
            return self.stop(post_stopped=True)
        if self._retry_attempts >= MAX_RETRY_ATTEMPTS:
            return self.stop(post_stopped=True)

        self._retry_attempts += 1
        self._state = State.LOADING
        return ScheduleRetry(
            generation=self._generation,
            delay=retry_delay(self._retry_attempts),
            url=self._url,
            attempt=self._retry_attempts,
            max_attempts=MAX_RETRY_ATTEMPTS,
        )
