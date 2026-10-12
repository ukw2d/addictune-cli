from addictune_sdk import Client
from addictune_sdk.models.mixshow import MixShow, ShowEpisode
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import Footer, Label

from ...audio.state import State
from ..presentation import BINDING_PLAY
from ..typed_nodes import AppNode
from ..utils import mark_playing
from ..widgets.media_list import ListSpec, MediaList, ModelItem, selected_child
from ..widgets.playback_bar import PlaybackBar
from .dialog import DialogScreen


class EpisodeSelected(Message):
    def __init__(self, episode: ShowEpisode) -> None:
        self.episode = episode
        super().__init__()


class EpisodeItem(AppNode, ModelItem):
    def __init__(self, episode: ShowEpisode) -> None:
        super().__init__(episode, EpisodeList.spec)

    @property
    def episode(self) -> ShowEpisode:
        return self.model

    def on_mount(self) -> None:
        if self.app.playing_episode_id == self.episode.id:
            bar = self.app.query_one(PlaybackBar)
            self.add_class("suspended" if bar.state == State.PAUSED else "playing")


class EpisodeList(MediaList):
    BINDINGS = [Binding("enter", "select_cursor", BINDING_PLAY, show=True)]
    item_type = EpisodeItem
    spec = ListSpec(
        label=lambda e: e.name, model_id=lambda e: e.id, message=EpisodeSelected
    )

    @property
    def episodes(self) -> tuple[ShowEpisode, ...]:
        return self.models

    def load_episodes(self, client: Client, network: str, show_id: int) -> None:
        self.show(
            f"episodes:{network}:{show_id}",
            client.network(network).mixshows.iter_episodes(show_id),
        )


class EpisodesScreen(AppNode, DialogScreen):
    DEFAULT_CSS = """
EpisodesScreen {
    #episodes-dialog {
        width: 60;
        height: 24;
    }

    #episodes-list {
        height: 1fr;
    }
}
    """

    def __init__(self, show: MixShow, network: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self._show = show
        self._network = network

    def compose(self) -> ComposeResult:
        with Vertical(id="episodes-dialog", classes="modal-dialog"):
            yield Label(self._show.name, id="episodes-title", classes="dialog-heading")
            yield EpisodeList(id="episodes-list")
            yield Footer()

    def on_mount(self) -> None:
        client: Client = self.app.client
        self.query_one(EpisodeList).load_episodes(client, self._network, self._show.id)

    def on_episode_selected(self, message: EpisodeSelected) -> None:
        episodes = self.query_one(EpisodeList)
        self.app._playback_service.play_episode(
            message.episode, self._show, self._network, episodes.episodes
        )
        mark_playing(self, selected_child(episodes))
