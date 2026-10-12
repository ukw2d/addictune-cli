import logging
import socket
import ssl
import threading
import time
from collections.abc import Callable, Iterator
from urllib.parse import urljoin, urlparse

from .protocol import AudioStreamInfo

_log = logging.getLogger("audio.stream")

_OPEN_TIMEOUT = (5.0, 2.0)
_BLOCK_FRAMES = 2048
_ICY_CONNECT_TIMEOUT = 10.0
_ICY_READ_TIMEOUT = 2.0
# A live stream delivers data every second or so, so silence this long means
# the connection is gone rather than slow. It bounds the dead air before the
# player exits and the app reconnects, so it is deliberately short.
_ICY_STALL_TIMEOUT = 6.0
_ICY_HEADER_LIMIT = 16384
_ICY_REDIRECTS = 3
_REDIRECT_CODES = {301, 302, 303, 307, 308}
_ICY_REQUEST_HEADERS = {
    "Icy-MetaData": "1",
    "User-Agent": "addictune",
    "Connection": "close",
}


def _packed_audio_bytes(frame) -> bytes:
    """Return only the logical bytes of a packed audio frame.

    PyAV pads planes to SIMD-aligned sizes; using the whole plane buffer
    injects silent bytes into the stream, causing audible micro-glitches.
    """
    size = frame.samples * frame.layout.nb_channels * frame.format.bytes
    return bytes(memoryview(frame.planes[0])[:size])


class Stream:
    """One opened URL: metadata up front, float32 chunks with live volume.

    Everything here runs in the player's decode thread.
    """

    def __init__(
        self,
        url: str,
        *,
        live: bool,
        start_at: float,
        sample_rate: int | None,
        volume: float,
        stop: threading.Event,
        on_title: Callable[[str], None] | None,
    ) -> None:
        import av
        import av.filter

        self._av = av
        self._stop = stop
        self._source = (
            _open_icy_audio_source(url, on_title, stop)
            if live and on_title is not None
            else None
        )
        try:
            self._container = av.open(self._source or url, timeout=_OPEN_TIMEOUT)
            audio = next(
                (s for s in self._container.streams if s.type == "audio"), None
            )
            if audio is None:
                raise ValueError("No audio stream")
            self._audio = audio
            self.info = AudioStreamInfo(
                channels=audio.channels,
                sample_rate=audio.sample_rate,
                layout=audio.layout.name,
                duration=_duration(self._container, audio),
                codec_name=audio.codec_context.name,
                bit_rate=audio.bit_rate
                or audio.codec_context.bit_rate
                or self._container.bit_rate
                or None,
            )
            self.channels = audio.channels
            self.sample_rate = sample_rate or audio.sample_rate
            layout = self.info.layout or ("stereo" if self.channels >= 2 else "mono")
            self._resampler = av.AudioResampler(
                format="flt", layout=layout, rate=self.sample_rate
            )
            self._graph = av.filter.Graph()
            src = self._graph.add_abuffer(
                format="flt",
                layout=layout,
                sample_rate=self.sample_rate,
                time_base=f"1/{self.sample_rate}",
            )
            # Gain is set before the first frame; a late set_volume would let
            # one chunk out at full scale, which is audible as a burst.
            self._volume_filter = self._graph.add("volume", f"volume={volume}")
            sink = self._graph.add("abuffersink")
            src.link_to(self._volume_filter)
            self._volume_filter.link_to(sink)
            self._graph.configure()
            self._volume = volume
            if start_at > 0 and not live:
                self._container.seek(int(start_at * 1_000_000))
        except Exception:
            self.close()
            raise

    def set_volume(self, volume: float) -> None:
        if volume != self._volume:
            self._volume_filter.process_command("volume", f"{volume}")
            self._volume = volume

    def chunks(self) -> Iterator[bytes]:
        """Yield float32 bytes in blocks of ``_BLOCK_FRAMES`` frames."""
        size = _BLOCK_FRAMES * self.channels * 4
        buf = bytearray()
        try:
            for packet in self._container.demux(self._audio):
                if self._stop.is_set():
                    return
                for frame in packet.decode():
                    for resampled in self._resampler.resample(frame):
                        buf.extend(self._filtered(resampled))
                    while len(buf) >= size:
                        yield bytes(buf[:size])
                        del buf[:size]
                        if self._stop.is_set():
                            return
            for resampled in self._resampler.resample(None):
                buf.extend(self._filtered(resampled))
            if buf and not self._stop.is_set():
                yield bytes(buf)
        except self._av.FFmpegError as exc:
            _log.error("decode failed: %s", exc)
            raise

    def _filtered(self, frame) -> bytes:
        self._graph.push(frame)
        out = bytearray()
        while True:
            try:
                out.extend(_packed_audio_bytes(self._graph.pull()))
            except (self._av.BlockingIOError, self._av.EOFError):
                return bytes(out)

    def close(self) -> None:
        container = getattr(self, "_container", None)
        if container is not None:
            container.close()
        if self._source is not None:
            self._source.close()


def _duration(container, stream) -> float | None:
    if stream.duration is not None and stream.time_base is not None:
        value = float(stream.duration * stream.time_base)
        if value > 0:
            return value
    if container.duration and container.duration > 0:
        return container.duration / 1_000_000
    return None


class _IcyAudioSource:
    """File-like audio stream that strips ICY metadata from one HTTP connection."""

    def __init__(
        self,
        sock: socket.socket,
        metaint: int,
        on_metadata: Callable[[str], None],
        stop: threading.Event | None,
    ) -> None:
        self._sock = sock
        self._metaint = metaint
        self._on_metadata = on_metadata
        self._stop = stop
        self._audio_until_meta = metaint
        self._last_title: str | None = None
        self._closed = False
        self._ended = False

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return False

    def read(self, size: int = -1) -> bytes:
        target = 8192 if size is None or size < 0 else size
        out = bytearray()
        while len(out) < target and not self._stopped():
            if self._audio_until_meta == 0:
                if not self._read_metadata():
                    break
                self._audio_until_meta = self._metaint
                continue
            chunk = self._recv(min(target - len(out), self._audio_until_meta))
            if not chunk:
                break
            out.extend(chunk)
            self._audio_until_meta -= len(chunk)
        return bytes(out)

    def close(self) -> None:
        self._closed = True
        try:
            self._sock.close()
        except OSError:
            pass

    def _stopped(self) -> bool:
        return self._closed or self._ended or bool(self._stop and self._stop.is_set())

    def _read_metadata(self) -> bool:
        if not (length := self._recv_exact(1)):
            return False
        if (meta := self._recv_exact(length[0] * 16)) is None:
            return False
        title = _parse_stream_title(meta)
        if title and title != self._last_title:
            self._last_title = title
            self._on_metadata(title)
        return True

    def _recv_exact(self, size: int) -> bytes | None:
        out = bytearray()
        while len(out) < size and not self._stopped():
            chunk = self._recv(size - len(out))
            if not chunk:
                return None
            out.extend(chunk)
        return bytes(out)

    def _recv(self, size: int) -> bytes:
        """Read from the socket, or return b"" once the stream is over.

        The end has to *latch*: libav answers a short read by reading again, so
        a deadline held only in this frame would restart on every retry and the
        source would never report EOF -- leaving the player alive on a dead
        socket, silent, with the app still believing it was playing.
        """
        deadline = time.perf_counter() + _ICY_STALL_TIMEOUT
        while not self._stopped():
            try:
                if chunk := self._sock.recv(size):
                    return chunk
            except TimeoutError:
                if time.perf_counter() < deadline:
                    continue
                _log.warning(
                    "icy stream stalled for %.0fs with no data; treating as EOF",
                    _ICY_STALL_TIMEOUT,
                )
            self._ended = True
            break
        return b""


def _icy_request(parsed) -> bytes:
    path = parsed.path or "/"
    if parsed.query:
        path += f"?{parsed.query}"
    headers = {"Host": parsed.netloc, **_ICY_REQUEST_HEADERS}
    head = f"GET {path} HTTP/1.0\r\n" + "".join(
        f"{k}: {v}\r\n" for k, v in headers.items()
    )
    return f"{head}\r\n".encode("latin1")


def _open_icy_audio_source(
    url: str,
    on_metadata: Callable[[str], None],
    stop: threading.Event | None,
) -> _IcyAudioSource | None:
    """Return an ICY-stripping source, or None if the server has no ICY metadata."""
    for _ in range(_ICY_REDIRECTS + 1):
        parsed = urlparse(url)
        host = parsed.hostname
        if not host:
            return None
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        sock: socket.socket | None = None
        try:
            sock = socket.create_connection((host, port), timeout=_ICY_CONNECT_TIMEOUT)
            if parsed.scheme == "https":
                sock = ssl.create_default_context().wrap_socket(
                    sock, server_hostname=host
                )
            sock.settimeout(_ICY_READ_TIMEOUT)
            sock.sendall(_icy_request(parsed))
            status, headers = _read_http_headers(sock)
            if status in _REDIRECT_CODES and (location := headers.get("location")):
                url = urljoin(url, location)
                sock.close()
                continue
            if not (metaint := headers.get("icy-metaint", "")).isdigit():
                sock.close()
                return None
            return _IcyAudioSource(sock, int(metaint), on_metadata, stop)
        except OSError as exc:
            _log.debug("icy metadata stream unavailable: %r", exc)
            if sock is not None:
                sock.close()
            return None
    return None


def _read_http_headers(sock: socket.socket) -> tuple[int, dict[str, str]]:
    raw = bytearray()
    while b"\r\n\r\n" not in raw and len(raw) < _ICY_HEADER_LIMIT:
        chunk = sock.recv(1)
        if not chunk:
            break
        raw.extend(chunk)
    lines = raw.decode("latin1", "replace").split("\r\n")
    parts = lines[0].split() if lines else []
    status = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    headers = {}
    for line in lines[1:]:
        key, sep, value = line.partition(":")
        if sep:
            headers[key.strip().lower()] = value.strip()
    return status, headers


def _parse_stream_title(meta: bytes) -> str | None:
    text = meta.split(b"\x00", 1)[0].decode("utf-8", "replace")
    marker = "StreamTitle='"
    start = text.find(marker)
    if start < 0:
        return None
    start += len(marker)
    end = text.find("';", start)
    if end < 0:
        end = text.find("'", start)
    title = text[start:end].strip() if end >= 0 else ""
    return title or None
