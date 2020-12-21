# coding: utf-8
#
# Copyright © 2020 melmorabity
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2 of the License, or (at your option) any later
# version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with
# this program; if not, write to the Free Software Foundation, Inc., 51
# Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.

from __future__ import unicode_literals
import logging

from multiprocessing.pool import ThreadPool

try:
    from multiprocessing import cpu_count
except ImportError:

    def cpu_count():
        # type: () -> int
        return 1


try:
    from typing import Dict
    from typing import Optional
    from typing import Text
    from typing import Union
except ImportError:
    pass

try:
    from urllib.parse import parse_qsl
    from urllib.parse import urlencode
except ImportError:
    from urlparse import parse_qsl
    from urllib import urlencode

import xbmc  # pylint: disable=import-error
from xbmcaddon import Addon  # pylint: disable=import-error
from xbmcgui import Dialog  # pylint: disable=import-error
from xbmcgui import ListItem  # pylint: disable=import-error
from xbmcgui import Window  # pylint: disable=import-error
import xbmcplugin  # pylint: disable=import-error

from resources.lib.api import BouyguesTV
from resources.lib.api import BouyguesTVException
from resources.lib.api import BouyguesTVLoginException
from resources.lib.api import BouyguesTVUnknownChannelException
from resources.lib.api import ParsedItem
import resources.lib.kodilogging

resources.lib.kodilogging.config()

_LOGGER = logging.getLogger(__name__)


# pylint: disable=too-few-public-methods
class BouyguesTVAddon:
    _ADDON_ID = "plugin.video.bouyguestv"
    _ADDON = Addon()

    _ACCESS_TOKEN_PROPERTY = "{}.access_token".format(_ADDON_ID)
    _ID_TOKEN_PROPERTY = "{}.id_token".format(_ADDON_ID)

    def __init__(self, base_url, handle, params):
        # type: (Text, int, Text) -> None

        self._base_url = base_url
        self._handle = handle
        self._params = self._params_to_dict(params)

        if not self._ADDON.getSetting("username"):
            self._ADDON.openSettings()

        username = self._ADDON.getSetting("username")
        password = self._ADDON.getSetting("password")
        access_token = (
            Window(10000).getProperty(self._ACCESS_TOKEN_PROPERTY) or None
        )
        id_token = Window(10000).getProperty(self._ID_TOKEN_PROPERTY) or None
        cache_name = "special://profile/addon_data/{}/requests_cache".format(
            self._ADDON_ID
        )

        self._api = BouyguesTV(
            username,
            password,
            access_token=access_token,
            id_token=id_token,
            cache_name=xbmc.translatePath(cache_name),
        )

    @staticmethod
    def _params_to_dict(params):
        # type: (Optional[Text]) -> Dict[Text, Text]

        # Parameter string starts with a '?'
        return dict(parse_qsl(params[1:])) if params else {}

    def _build_url(self, **query):
        # type: (Union[int, Text]) -> Text

        # Remove None values from the query string
        return "{}?{}".format(
            self._base_url,
            urlencode(dict((k, v) for k, v in list(query.items()) if v)),
        )

    def _add_listitem(self, channel_item):
        # type: (Optional[ParsedItem]) -> None

        if not channel_item:
            return

        _LOGGER.debug("Add ListItem %s", channel_item)

        listitem = ListItem(channel_item.label, offscreen=True)
        listitem.setInfo("video", channel_item.info)
        listitem.setArt(channel_item.art)
        listitem.setProperty("isPlayable", "true")

        xbmcplugin.addDirectoryItem(
            self._handle,
            self._build_url(**channel_item.url),
            listitem,
            isFolder=False,
        )

    def _mode_channels(self):
        # type: () -> None

        xbmcplugin.setContent(self._handle, "videos")

        pool = ThreadPool(processes=5 * cpu_count())

        for channel in self._api.get_channels():
            pool.apply_async(
                self._add_listitem, [self._api.get_channel_item(channel)]
            )

        pool.close()
        pool.join()

    def _mode_watch(self):
        # type: () -> None

        channel_name = self._params.get("channel")
        if not channel_name:
            raise BouyguesTVUnknownChannelException(channel_name)

        video_url = self._api.get_channel_stream_url(channel_name)
        if not video_url:
            raise BouyguesTVException(
                "Unable to retrieve stream for channel {}".format(channel_name)
            )

        xbmcplugin.setResolvedUrl(
            self._handle, True, ListItem(path=video_url, offscreen=True),
        )

        Window(10000).setProperty(
            self._ACCESS_TOKEN_PROPERTY, self._api.access_token or ""
        )
        Window(10000).setProperty(
            self._ID_TOKEN_PROPERTY, self._api.id_token or ""
        )

    def run(self):
        # type: () -> None

        mode = self._params.get("mode")
        succeeded = True

        try:
            if mode == "watch":
                self._mode_watch()
            else:
                self._mode_channels()
        except BouyguesTVLoginException as ex:
            _LOGGER.error(ex)
            Dialog().ok(
                self._ADDON.getLocalizedString(30200),
                self._ADDON.getLocalizedString(30201),
            )
            succeeded = False
        finally:
            xbmcplugin.endOfDirectory(self._handle, succeeded=succeeded)
