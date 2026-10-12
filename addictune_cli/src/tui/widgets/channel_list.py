from addictune_sdk.models.channel import Channel
from textual.message import Message

from ..types import ChannelView
from .media_list import ListSpec, MediaList, ModelItem


class ChannelItem(ModelItem):
    """Row for a ChannelView; built by ChannelsService from the in-memory list."""

    def __init__(self, view: ChannelView) -> None:
        super().__init__(view, ChannelList.spec)

    @property
    def channel(self) -> Channel:
        return self.model.channel


class ChannelList(MediaList):
    """Channels are loaded whole by ChannelsService; no paging source."""

    class ChannelSelected(Message):
        def __init__(self, channel: Channel) -> None:
            self.channel = channel
            super().__init__()

    item_type = ChannelItem
    spec = ListSpec(
        label=lambda view: view.channel.name,
        model_id=lambda view: view.channel.id,
        message=lambda view: ChannelList.ChannelSelected(view.channel),
        followed=lambda view: view.favorite,
        live_badge=True,
    )
