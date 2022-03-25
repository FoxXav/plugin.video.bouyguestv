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

from __future__ import division
from __future__ import unicode_literals
from collections import OrderedDict
from datetime import date
from datetime import datetime
import re
import time

try:
    from typing import Any
    from typing import Dict
    from typing import List
    from typing import NamedTuple
    from typing import Optional
    from typing import Text
    from typing import Tuple

    Art = Dict[Text, Optional[Text]]  # pylint: disable=unsubscriptable-object
    Url = Dict[Text, Text]

    ParsedItem = NamedTuple(
        "ParsedItem",
        [
            ("label", Text),
            ("url", Url),
            ("info", Dict[Text, Any]),
            ("art", Art),
        ],
    )
except ImportError:
    from collections import namedtuple  # pylint: disable=ungrouped-imports

    ParsedItem = namedtuple(  # type: ignore
        "ParsedItem", ["label", "url", "info", "art"]
    )

try:
    from urllib.parse import parse_qsl
    from urllib.parse import urlparse
except ImportError:
    from urlparse import parse_qsl
    from urlparse import urlparse

from dateutil.parser import isoparse
import dateutil.tz

try:
    import pyjwt as jwt
except ImportError:
    import jwt
from requests import Response
from requests.exceptions import RequestException
from requests_cache import CachedSession


class BouyguesTVException(Exception):
    pass


class BouyguesTVLoginException(BouyguesTVException):
    pass


class BouyguesTVUnknownChannelException(BouyguesTVException):
    def __init__(self, channel):
        # type: (Optional[Text]) -> None

        super(BouyguesTVUnknownChannelException, self).__init__(
            'Unknown channel "{}"'.format(channel or "")
        )


class BouyguesTV:
    _USER_AGENT = (
        "Mozilla/5.0 (X11; Fedora; Linux x86_64; rv:84.0) "
        "Gecko/20100101 Firefox/84.0"
    )
    _LOGIN_URL = "https://www.mon-compte.bouyguestelecom.fr/cas/login"
    _OAUTH2_URL = "https://oauth2.bouyguestelecom.fr/authorize"
    _BASE_URL = "https://www.bouyguestelecom.fr/tv-direct"
    _CHANNEL_LIST_URL = "{}/data/list-chaines.json".format(_BASE_URL)
    _STREAM_API_URL = (
        "https://8wwwu6s5l4.execute-api.eu-west-1.amazonaws.com/Prod/get-url"
    )
    _EPG_BASE_URL = "{}/data/epg".format(_BASE_URL)
    _EPG_TIMEZONE = dateutil.tz.gettz("Europe/Paris")

    # pylint: disable=too-many-arguments
    def __init__(
        self,
        lastname, 
        username,
        password,
        access_token=None,
        id_token=None,
        cache_name="bouyguestv",
    ):
        # type: (Text, Text, Optional[Text], Optional[Text], Text) -> None
        self._lastname = lastname
        self._username = username
        self._password = password

        self._access_token = access_token
        self._id_token = id_token

        self._session = CachedSession(
            cache_name=cache_name, backend="sqlite", expire_after=21600
        )
        self._session.headers.update({"User-Agent": self._USER_AGENT})
        self._session.hooks = {"response": [self._requests_raise_status]}

        self._channels = self._get_channels()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        if self._session:
            self._session.close()

    @property
    def access_token(self):
        # type: () -> Optional[Text]

        return self._access_token

    @property
    def id_token(self):
        # type: () -> Optional[Text]

        return self._id_token

    @staticmethod
    def _requests_raise_status(response, *_args, **_kwargs):
        # type: (Response, Any, Any) -> None

        try:
            response.raise_for_status()
        except RequestException as ex:
            if response.status_code == 401:
                raise BouyguesTVLoginException(ex)
            raise ex

    def _parse_id_token(self):
        # type: () -> Tuple[int, Optional[Text]]

        jwt_payload = jwt.decode(self._id_token, verify=False)
        return jwt_payload.get("exp", 0), jwt_payload.get("id_personne")

    def _login(self):
        # type: () -> None

        response = self._session.get(self._LOGIN_URL)
        payload = dict(
            re.findall(
                r'<input type="hidden" name="(.*?)" value="(.*?)"/>',
                response.text,
            )
        )
        payload["lastname"] = self._lastname
        payload["username"] = self._username
        payload["password"] = self._password

        self._session.post(self._LOGIN_URL, data=payload)

    def _refresh_token(self):
        # type: () -> None

        if self._access_token and self._id_token:
            id_token_exp, _ = self._parse_id_token()
            now = time.mktime(datetime.now().timetuple())
            if id_token_exp and id_token_exp > now:
                return

        self._login()

        payload = {
            "client_id": "a360.bouyguestelecom.fr",
            "response_type": "id_token token",
            "redirect_uri": "https://www.bouyguestelecom.fr/mon-compte/",
        }

        response = self._session.post(self._OAUTH2_URL, data=payload)
        fragment = dict(parse_qsl(urlparse(response.url).fragment))
        self._access_token = fragment.get("access_token") or ""
        self._id_token = fragment.get("id_token") or ""

        if not self._access_token or not self._id_token:
            raise BouyguesTVException("Unable to retrieve token")

    def _get_channels(self):
        # type: () -> Dict[Text, Any]

        return OrderedDict(
            (c.get("title"), c)
            for c in self._session.get(self._CHANNEL_LIST_URL)
            .json()
            .get("body", [])
        )

    def get_channels(self):
        # type: () -> List[Text]

        return list(self._channels.keys())

    @classmethod
    def _epg_datetime(cls, epg_datetime):
        # type: (Optional[Text]) -> Optional[datetime]

        if not epg_datetime:
            return None

        return isoparse(
            epg_datetime  # type: ignore
        ).replace(
            tzinfo=cls._EPG_TIMEZONE
        )

    def _get_channel_epg(self, epg_channel_number, day):
        # type: (int, date) -> List[Dict[Text, Any]]

        params = {"d": "{}{}{}".format(day.year, day.month - 1, day.day)}
        epg_url = "{}/{}.json".format(self._EPG_BASE_URL, epg_channel_number)

        return (
            self._session.get(epg_url, params=params)
            .json()
            .get("programs", [])
        )

    def get_channel_item(self, channel):
        # type: (Text) -> Optional[ParsedItem]

        now = (
            datetime.utcnow()
            .replace(tzinfo=dateutil.tz.UTC)
            .astimezone(tz=self._EPG_TIMEZONE)  # type: ignore
        )

        if channel not in self._channels:
            raise BouyguesTVUnknownChannelException(channel)

        epg_channel_number = self._channels[channel].get("epgChannelNumber")
        if not epg_channel_number:
            return None

        info = {}  # type: Dict[Text, Any]

        epg = self._get_channel_epg(epg_channel_number, now.date())

        # Get current program
        for program in epg:
            start_time = self._epg_datetime(program.get("fullStartTime"))
            end_time = self._epg_datetime(program.get("fullEndTime"))

            if start_time and end_time and start_time <= now < end_time:
                info["duration"] = int((end_time - start_time).total_seconds())
                break
        else:
            program = {}

        info["genre"] = program.get("genre")
        info["year"] = program.get("productionDate")
        info["episode"] = program.get("episodeNumber")
        info["season"] = program.get("seasonNumber")

        if program.get("pressRank"):
            info["rating"] = 2 * float(program["pressRank"])

        # Don't mark live streams as read once played
        info["playcount"] = 0
        info["cast"] = [
            (
                "{} {}".format(
                    c.get("firstName", ""), c.get("lastName", "")
                ).strip(),
                c.get("role"),
            )
            for c in program.get("characters", [])
        ]
        info["director"] = program.get("realisateur")
        info["plot"] = program.get("summary")
        info["title"] = program.get("title") or program.get("longtitle")

        if info["episode"] or info["season"]:
            info["mediatype"] = "episode"
        else:
            info["mediatype"] = "movie"

        url_media = program.get("urlMedia")
        if url_media and not url_media.startswith("http"):
            url_media = "{}/{}".format(self._BASE_URL, url_media)

        art = {
            "fanart": url_media,
            "icon": self._channels[channel].get("logoUrl"),
            "landscape": url_media,
        }  # type: Art

        url = {"mode": "watch", "channel": channel}  # type: Url

        label = "[B]{}[/B]".format(channel)
        if info.get("title"):
            label += " – {}".format(info["title"])

        return ParsedItem(label, url, info, art)

    def get_channel_stream_url(self, channel):
        # type: (Text) -> Text

        if channel not in self._channels:
            raise BouyguesTVUnknownChannelException(channel)

        channel_url = self._channels.get(channel, {}).get("StreamURL")

        self._refresh_token()

        _, id_personne = self._parse_id_token()

        payload = {
            "id_personne": id_personne,
            "channel_url": channel_url,
        }
        headers = {
            "authorization": "Bearer {}".format(self._access_token),
            "origin": "https://www.bouyguestelecom.fr",
        }

        response = self._session.post(
            self._STREAM_API_URL, json=payload, headers=headers,
        )

        return response.json().get("urlFlux")
