from urllib.parse import urlsplit

from ...audio.protocol import AudioStreamInfo
from ..presentation import VOLUME_ICON, VOLUME_MUTED

StreamQuality = tuple[str, str]

_LIVE_QUALITY_BY_PATH = {
    "premium_high": ("MP3", 320),
    "premium": ("AAC", 128),
    "premium_medium": ("AAC", 64),
}


def format_time_pair(elapsed: int, duration: int | None) -> str:
    has_hours = elapsed >= 3600 or (duration is not None and duration >= 3600)
    elapsed_text = _format_time(elapsed, has_hours=has_hours)
    duration_text = (
        _format_time(duration, has_hours=has_hours)
        if duration is not None
        else ("-:--:--" if has_hours else "--:--")
    )
    return f"{elapsed_text}/{duration_text}"


def format_volume_label(volume: int, *, muted: bool) -> str:
    return VOLUME_MUTED if muted else f"{VOLUME_ICON} {volume}"


def stream_quality_from_url(url: str) -> StreamQuality | None:
    """Return the SDK-declared live quality tier encoded in a stream URL."""
    segments = set(urlsplit(url).path.split("/"))
    for path, (codec, bitrate) in _LIVE_QUALITY_BY_PATH.items():
        if path in segments:
            return f"{codec} · {bitrate}k", f"Source: {codec} · {bitrate} kbps"
    return None


def format_stream_quality(info: AudioStreamInfo) -> StreamQuality:
    """Return a compact source-quality label and a detailed tooltip."""
    # Decoder names carry suffixes ("mp3float", "aac_fixed"); show the codec only.
    codec = (info.codec_name or "").split("_", 1)[0].upper().removesuffix("FLOAT")
    bitrate = round(info.bit_rate / 1000) if info.bit_rate else None
    sample_rate = f"{info.sample_rate / 1000:g} kHz"
    label = (
        f"{codec} · {bitrate}k"
        if codec and bitrate
        else f"{codec} · {sample_rate}"
        if codec
        else f"{bitrate} kbps"
        if bitrate
        else sample_rate
    )
    layout = (
        info.layout.replace("_", " ").title()
        if info.layout
        else "Mono"
        if info.channels == 1
        else "Stereo"
        if info.channels == 2
        else f"{info.channels} channels"
    )
    details = filter(None, (codec, f"{bitrate} kbps" if bitrate else None, sample_rate, layout))
    return label, "Source: " + " · ".join(details)


def _format_time(seconds: int | None, *, has_hours: bool) -> str:
    seconds = max(0, seconds or 0)
    minutes, secs = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if has_hours:
        return f"{hours}:{minutes:02}:{secs:02}"
    return f"{minutes:02}:{secs:02}"
