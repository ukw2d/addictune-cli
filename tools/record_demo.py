"""Record the README/Reddit demo by driving the real app headless with Textual's Pilot.

Each step presses keys or clicks, then exports SVG frames of what the UI shows.
Frames are rasterised with ``resvg`` and encoded with ``ffmpeg``. It signs in with
the credentials already saved by the app and plays real audio at the volume in
your settings.

Panel and screen animations are captured on a virtual clock that advances exactly
1/30 s per frame, so they play back smoothly however slow the export is.

    uv run python tools/record_demo.py --probe   # one frame, to check the setup
    uv run python tools/record_demo.py           # full demo -> build/demo/demo.mp4
    uv run python tools/record_demo.py --gif     # re-encode that MP4 -> docs/assets/demo.gif

Requires ``resvg`` and ``ffmpeg`` on PATH and the Fira Code font (the SVG export uses it).
"""

import argparse
import asyncio
import shutil
import subprocess
import time
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from textual import _time
from textual.widgets import ListView, Static

from addictune_cli.src.audio.state import State
from addictune_cli.src.tui.app import TAB_LISTS, AddictuneApp
from addictune_cli.src.tui.screens.episodes import EpisodeList
from addictune_cli.src.tui.services.images import fetch_pixels
from addictune_cli.src.tui.types import MediaStatus
from addictune_cli.src.tui.widgets.channel_list import ChannelList
from addictune_cli.src.tui.widgets.media_info import MediaInfoPanel, channel_media_info
from addictune_cli.src.tui.widgets.playback_bar import PlaybackBar

OUT = Path("build/demo")
GIF = Path("docs/assets/demo.gif")
SIZE = (120, 34)
WIDTH_PX = 1480
FPS = 30
STEP = 1 / FPS

# Pacing (seconds). Each list move is held long enough to read the highlighted row.
HOLD_ROW = 0.75
HOLD_PANEL = 1.6
HOLD_TAB = 1.5
HOLD_PLAYING = 2.2
HOLD_END = 3.0
TYPING = 0.14
SEARCH_TERM = "ASOT"


class Recorder:
    def __init__(self, app: AddictuneApp) -> None:
        self.app = app
        self.frames: list[list] = []  # [svg path, hold seconds]

    def snap(self, hold: float = STEP) -> None:
        svg = OUT / "svg" / f"{len(self.frames):04d}.svg"
        svg.write_text(self.app.export_screenshot(title="addictune"), encoding="utf-8")
        self.frames.append([svg, hold])

    def freeze(self, seconds: float) -> None:
        """Keep showing the current frame for a while."""
        self.frames[-1][1] += seconds

    async def live(
        self, until: Callable[[], bool], *, minimum: float = 0.0, cap: float = 12.0
    ) -> None:
        """Capture in real time until *until* holds and *minimum* seconds passed."""
        start = last = time.monotonic()
        first = len(self.frames)
        while True:
            await asyncio.sleep(0.01)
            now = time.monotonic()
            self.snap()
            if len(self.frames) - 1 > first:
                self.frames[-2][1] = now - last
            last = now
            elapsed = now - start
            if elapsed >= cap or (elapsed >= minimum and until()):
                break

    async def animated(self, action: Callable[[], Awaitable[None]]) -> None:
        """Run *action* while stepping Textual's animations on a virtual clock."""
        animator = self.app.animator
        clock = _time.get_time()
        animator._get_time = lambda: clock
        task = asyncio.create_task(action())
        frames = 0
        while frames < 3 or not task.done() or animator._animations:
            if frames > 4 * FPS:
                break
            clock += STEP
            await asyncio.sleep(0.04)
            self.snap()
            frames += 1
        await task
        del animator._get_time

    def encode(self) -> Path:
        png = OUT / "png"
        png.mkdir()

        def rasterise(item: tuple[int, list]) -> str:
            index, (svg, _) = item
            image = png / f"{index:04d}.png"
            subprocess.run(
                ["resvg", "-w", str(WIDTH_PX), str(svg), str(image)],
                check=True,
                stderr=subprocess.DEVNULL,
            )
            return image.resolve().as_posix()

        with ThreadPoolExecutor() as pool:
            images = list(pool.map(rasterise, enumerate(self.frames)))
        lines = ["ffconcat version 1.0"]
        for image, (_, hold) in zip(images, self.frames, strict=True):
            lines += [f"file '{image}'", f"duration {hold:.4f}"]
        lines.append(f"file '{images[-1]}'")
        (OUT / "frames.txt").write_text("\n".join(lines), encoding="utf-8")
        video = OUT / "demo.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-safe", "0", "-f", "concat",
             "-i", str(OUT / "frames.txt"),
             "-vf", f"fps={FPS},scale=trunc(iw/2)*2:trunc(ih/2)*2",
             "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(video)],
            check=True,
        )  # fmt: skip
        return video


def make_gif(video: Path = OUT / "demo.mp4", gif: Path = GIF) -> Path:
    """Re-encode *video* as the README GIF: 960 px wide, 15 fps, 128-colour palette."""
    filters = (
        "fps=15,scale=960:-1:flags=lanczos,split[a][b];"
        "[a]palettegen=max_colors=128:stats_mode=diff[p];"
        "[b][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle"
    )
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(video),
            "-vf",
            filters,
            str(gif),
        ],
        check=True,
    )
    return gif


def artwork_ready(app: AddictuneApp) -> bool:
    """True once the sidebar shows the artwork of the item it describes."""
    panel = app.query_one(MediaInfoPanel)
    if not panel.is_open or panel.media is None:
        return True
    loader = panel._image_loader
    image = panel.query_one(loader._image_selector, Static)
    return loader._displayed_url == panel.media.image_url and not image.loading


def live_channel_index(channels: ChannelList) -> int | None:
    for index, item in enumerate(channels.children):
        status = getattr(item, "status", None)
        if status is not None and status.status is MediaStatus.LIVE_NOW:
            return index
    return None


async def wait_for(condition: Callable[[], bool], timeout: float = 20) -> None:
    end = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > end:
            raise TimeoutError("timed out waiting for the UI")
        await asyncio.sleep(0.1)


async def demo(rec: Recorder, pilot) -> None:
    app = rec.app
    bar = app.query_one(PlaybackBar)
    channels = app.query_one("#channel-list", ChannelList)
    await wait_for(lambda: live_channel_index(channels) is not None)
    live = live_channel_index(channels)
    await pilot.pause()

    # Warm everything the recording will touch, off camera, so the clip shows the
    # app as it feels on a warm cache instead of first-load spinners.
    rows = [*channels.children[:10], channels.children[live]]
    urls = {channel_media_info(r.channel).image_url for r in rows}
    await asyncio.gather(*(fetch_pixels(u, 38, 19, app.client) for u in urls if u))
    for tab in ("mixshows", "playlists", "tracks"):
        await pilot.click(f"#{tab}")
        await wait_for(lambda s=TAB_LISTS[tab][0]: len(app.query_one(s)) > 0)
    await pilot.click("#channels")
    network = app.client.network(app.network)
    first_show = (await network.search.query(SEARCH_TERM)).shows.items[0]
    async for _ in network.mixshows.iter_episodes(first_show.id):
        break
    await pilot.pause()

    async def move(key: str) -> None:
        await pilot.press(key)
        await rec.live(lambda: artwork_ready(app), minimum=0.1)
        rec.freeze(HOLD_ROW)

    def playing() -> bool:
        return bar.state is State.PLAYING

    rec.snap()
    rec.freeze(1.0)

    # 1. Arrow down the channel list, then slide the info sidebar in.
    for _ in range(2):
        await move("down")
    await rec.animated(lambda: pilot.press("i"))
    await rec.live(lambda: artwork_ready(app), minimum=0.1)
    rec.freeze(HOLD_PANEL)
    for _ in range(2):
        await move("down")

    # 2. Arrow back to the LIVE NOW channel and start playback.
    while channels.index != live:
        await move("up" if channels.index > live else "down")
    rec.freeze(0.4)
    await pilot.press("enter")
    await rec.live(playing, minimum=0.5)
    rec.freeze(HOLD_PLAYING)

    # 3. Expanded player slides open, 4. the sidebar slides away.
    await rec.animated(lambda: pilot.press("e"))
    rec.freeze(HOLD_PANEL)
    await rec.animated(lambda: pilot.press("i"))
    rec.freeze(HOLD_PANEL)

    # 5. Visit each tab with the mouse; wait until its list has content.
    for tab in ("mixshows", "playlists", "tracks"):
        selector, _ = TAB_LISTS[tab]
        await rec.animated(lambda tab=tab: pilot.click(f"#{tab}"))
        await rec.live(lambda s=selector: len(app.query_one(s)) > 0, minimum=0.3)
        rec.freeze(HOLD_TAB)

    # 6. Global search: find "ASOT", open the mixshow, play its first episode.
    await rec.animated(lambda: pilot.press("ctrl+g"))
    rec.freeze(0.6)
    for char in SEARCH_TERM:
        await pilot.press(char)
        rec.snap(TYPING)
    rec.freeze(0.5)
    await pilot.press("enter")
    results = lambda: app.screen.query_one("#global-search-results", ListView)  # noqa: E731
    await rec.live(lambda: results().display and len(results()) > 0, minimum=0.3)
    rec.freeze(HOLD_TAB)
    await rec.animated(lambda: pilot.press("enter"))
    episodes = lambda: app.screen.query_one(EpisodeList)  # noqa: E731
    await rec.live(lambda: len(episodes()) > 0, minimum=0.3)
    rec.freeze(HOLD_TAB)
    await pilot.press("down")  # the dialog opens with no row highlighted
    await rec.live(lambda: episodes().index == 0, minimum=0.1)
    rec.freeze(HOLD_ROW)
    await pilot.press("enter")
    await rec.live(
        lambda: app.playing_episode_id is not None and playing(), minimum=0.5
    )
    rec.freeze(HOLD_PLAYING)

    # 7. Back out of the dialogs, then show the command palette.
    await rec.animated(lambda: pilot.press("escape"))
    rec.freeze(0.7)
    await rec.animated(lambda: pilot.press("escape"))
    rec.freeze(1.0)
    await rec.animated(lambda: pilot.press("ctrl+p"))
    rec.freeze(HOLD_END)


async def run(probe: bool) -> Path | None:
    app = AddictuneApp()
    rec = Recorder(app)
    async with app.run_test(size=SIZE) as pilot:
        if probe:
            await asyncio.sleep(8)
            rec.snap(1)
        else:
            await demo(rec, pilot)
        await pilot.press("s")
    return None if probe else rec.encode()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--gif", action="store_true", help="only re-encode the GIF")
    args = parser.parse_args()
    if args.gif:
        print(make_gif())
        return
    shutil.rmtree(OUT, ignore_errors=True)
    (OUT / "svg").mkdir(parents=True)
    video = asyncio.run(run(args.probe))
    if video:
        print(video)
        print(make_gif(video))


if __name__ == "__main__":
    main()
