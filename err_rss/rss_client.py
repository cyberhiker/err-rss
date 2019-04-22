import logging
from urllib.parse import urlsplit
import time

from retry import retry
import requests
import feedparser

from .login import Authenticator


def published_date(entry):
    return entry.get('published')


def header_matches_url(header, url):
    # Here we compare the end of the domain and the start of the path (if
    # present) to the header.
    __, domain, apath, *__ = urlsplit(url)
    parts = header.lstrip('*').split('/', 1)
    apath = apath.lstrip('/')
    if len(parts) == 2:
        # Domain and path in header. Match the path starts and domain ends.
        header_domain, header_path = parts
        return apath.startswith(header_path) and domain.endswith(header_domain)
    else:
        # Domain without os.path. Match the domain ends.
        header_domain, = parts
        return domain.endswith(header_domain)


class FeedReader:

    def __init__(self, http_session: requests.Session, url: str, authenticator: Authenticator, logger=None):
        self.session = http_session
        self.log = logger if logger else logging.getLogger(self.__class__.__name__)
        self.url = url
        self.authenticator = authenticator

    def _read_url(self, url: str):
        session = self.authenticator.login(session=self.session)
        return session.get(url)

    @retry(Exception, tries=3, delay=2)
    def read(self, url: str):
        """Read the RSS/Atom feed at the given url.
        If no feed can be found at the given url, return None.
        :param str url: url at which to find the feed
        :return: parsed feed or None
        """
        try:
            response = self._read_url(url=url)
            response.raise_for_status()
            feed = feedparser.parse(response.text)
            assert 'title' in feed['feed']
        except Exception as e:
            self.log.error(str(e))
            raise
        else:
            return feed

    def pick_recent_entries_from(self, title, entries, check_date):
        # Find the oldest and newest entries
        num_entries = len(entries)
        if num_entries == 1:
            newest = oldest = entries[0]
        elif num_entries == 2:
            oldest, newest = entries
        else:
            oldest, *__, newest = entries

        # Find recent entries
        def is_recent(entry):
            return entry.get('published_date') > check_date

        recent_entries = tuple(e for e in entries if is_recent(e))
        num_recent = len(recent_entries)

        if recent_entries:
            # Add recent entries to report
            about_then = check_date.humanize()
            self.log.info(f'[{title}] Found {num_recent} entries since {about_then}')
        else:
            self.log.info(f"[{title}] Found {num_entries} entries since {oldest['when']}, "
                          f"but none since {newest['when']}")

        return recent_entries
