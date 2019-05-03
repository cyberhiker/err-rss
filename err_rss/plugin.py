"""
Errbot plugin to redirect RSS feeds.
"""
import os
import logging
import threading
import configparser

import arrow
import requests
from errbot import BotPlugin, botcmd, arg_botcmd
import dateutil.parser as dparser

from .login import Authenticator
from .room_feed import Feed
from .config import DEFAULT_CONFIG, get_config_filepath
from .rss_client import FeedReader, header_matches_url, published_date


def since(target_time):
    target_time = arrow.get(target_time)
    return lambda entry: published_date(entry) > target_time


def read_date(dt):
    """This reads a date in an unknown format."""
    return arrow.get(dparser.parse(dt))


def try_method(f):
    try:
        return f()
    except Exception as e:
        logging.error('Thread failed with: {}'.format(str(e)))
        return None


class Rss(BotPlugin):
    """RSS Feeder plugin for Errbot."""
    def configure(self, configuration):
        config = DEFAULT_CONFIG
        if configuration:
            config.update(configuration)
        super().configure(config)

    def activate(self):
        super().activate()
        self.session = requests.Session()

        config_file_path = get_config_filepath()
        if config_file_path:
            self.read_ini(config_file_path)
        else:
            raise EnvironmentError('Could not find any configuration file.')

        self._feed_readers = {}

        # Manually use a timer, since the poller implementation in errbot
        # breaks if you try to change the polling interval.
        self.checker = None
        then = arrow.get()
        self.delta = arrow.get() - then
        self.check_feeds()

    def deactivate(self):
        super().deactivate()
        self.stop_checking_feeds()

    def read_ini(self, filepath):
        """Read and store the configuration in the ini file at fileos.path.

        Note: this method silently fails if given a nonsensicle filepath, but
        it does log the number of sections it read.

        :param str filepath: path to the ini file to use for configuration
        """
        self.ini = configparser.ConfigParser()
        self.ini.read(os.path.expanduser(filepath))
        self.log.info('Read {} sections from {}'.format(len(self.ini), filepath))

    def schedule_next_check(self):
        """Schedule the next feed check.

        This method ensures any pending check for new feed entries is canceled
        before scheduling the next one.
        """
        self.stop_checking_feeds()
        if self.interval:
            def job():
                return try_method(self.check_feeds)

            self.checker = threading.Timer(self.interval, job)
            self.checker.start()
            self.log.info('Scheduled next check in {}s'.format(self.interval))
        else:
            self.log.info('Scheduling disabled since interval is 0s.')

    def stop_checking_feeds(self):
        """Stop any pending check for new feed entries."""
        if self.checker:
            self.checker.cancel()
            self.log.info('Pending check canceled.')
        else:
            self.log.info('No pending checks to cancel.')

    @staticmethod
    def entry_format_function():
        return '[{title}]({link}) --- {when}'.format

    @property
    def feeds(self):
        """A dict with RSS feeds data."""
        if 'feeds' not in self:
            self['feeds'] = {}

        return self['feeds']

    def check_feeds(self, repeat=True):
        """Check for any new feed entries and report them to each corresponding room.

        :param bool repeat: whether or not to schedule the next check
        """
        start_time = arrow.get()
        self.log.info('Starting feed checker...')

        # Make sure to extend the interval if the last feed check took longer
        # than the interval, then schedule the next check. Only problem with
        # this is that it requires two checks to overlap before any adjustment
        # is realized.
        if self.delta.seconds >= self.interval:
            self.log.info(f'Increasing the interval from {self.interval}s to {self.delta.seconds}s due to '
                          'longer processing times')
            self.interval = self.delta.seconds

        if repeat:
            self.schedule_next_check()

        num_feeds = len(self.feeds)
        if num_feeds == 0:
            self.log.info('No feeds to check.')
            return

        self.log.info(f'Checking {num_feeds} feeds...')

        for title, feed in self.feeds.items():  # TODO: make this thread safe
            self._send_feed(title, feed)

        # Record the time needed for the current set of feeds.
        end_time = arrow.get()
        self.delta = end_time - start_time

    def _get_room_id(self, message):
        """ Return a room ID to identify the feed reports destinations."""
        if self.mode == 'telegram':
            if hasattr(message.frm, 'room'):
                return message.frm.room.id

            return message.frm.person
        else:
            raise ValueError('This plugin has not been implemented for '
                             'mode {}.'.format(self.mode))

    def _get_sender(self, message):
        """ Return a room ID to identify the feed reports destinations."""
        return message.frm if message.is_direct else message.to

    def add_feed(self, title, url):
        """ Add a feed object."""
        new_feed = Feed(title, url)

        with self.mutable('feeds') as feeds:
            feeds[title] = new_feed

    def add_room_to_feed(self, title, message, check_date):
        with self.mutable('feeds') as feeds:
            feeds[title].add_room(
                room_id=self._get_room_id(message),
                message=message,
                last_check=check_date
            )

    def remove_feed_from_room(self, title, message):
        room_id = self._get_room_id(message)

        with self.mutable('feeds') as feeds:
            feeds[title].remove_room(room_id=room_id)

            if not self.feeds[title].has_rooms():
                del self.feeds[title]

    def _get_feeds_from_url(self, url):
        for title, feed in self.feeds.items():
            if feed.url == url:
                yield feed

    def set_roomfeed_last_check(self, title, room_id, date):
        with self.mutable('feeds') as feeds:
            feeds[title].roomfeeds[room_id].last_check = date

    def _is_feed_in_room(self, title, room_id):
        if title not in self.feeds:
            return False
        return self.feeds[title].isin(room_id)

    def _find_url_ini_config(self, url):
        self.log.debug('Finding ini section for "{}"...'.format(url))
        for header, section in self.ini.items():
            if header_matches_url(header, url):
                config = dict(section)
                self.log.debug(f'Matched "{url}" to "{header}".')
                return config
        self.log.error(f'ERROR: Found no RSS config match for "{url}".')


    @property
    def startup_date(self):
        return read_date(self.config['START_DATE'])

    @property
    def interval(self):
        """Number of seconds between checks for new feed entries."""
        return self.config['INTERVAL']

    @interval.setter
    def interval(self, value):
        if value > 0:
            self.log.info(f'New update interval: {value}s')
            self.config['INTERVAL'] = value
            self.schedule_next_check()
        else:
            self.config['INTERVAL'] = 0
            self.log.info('Scheduling disabled.')
            self.stop_checking_feeds()

    def _send_feed(self, title, feed):
        """
        :param str title: title of the feed
        :param Feed feed: the feed object
        :return:
        """
        feed_content = self.read_feed(url=feed.url)
        if not feed_content:
            self.log.error(f'[{title}] No feed found!')
            return
        if not feed_content['entries']:
            self.log.info(f'[{title}] No entries yet.')
            return
        entries = feed_content['entries']
        # Touch up each entry.
        for entry in entries:
            entry['published'] = read_date(published_date(entry))
            entry['when'] = entry['published'].humanize()
        # sort entries
        entries.sort(key=published_date)
        # for each room will report the corresponding entries
        feed_reader = self._feed_reader(url=feed.url)
        for room_id, roomfeed in feed.roomfeeds.items():
            self.log.info(f'[{title}] Checking for entries for room {roomfeed.message.frm}.')
            recent_entries = feed_reader.pick_recent_entries_from(
                title=title,
                entries=entries,
                check_date=roomfeed.last_check
            )
            if recent_entries:
                self._send_entries_to_room(recent_entries, roomfeed)
                # Only update the last check time for this feed when there are recent entries.
                newest = recent_entries[-1]
                self.set_roomfeed_last_check(
                    title, room_id, newest['published'])
                self.log.info(f"[{title}] Updated room {room_id} last check time to {newest['when']}")

    def _send_entries_to_room(self, entries, roomfeed):
        """
        :param List[dict] entries:
        :param RoomFeed roomfeed:
        :return:
        """
        # Report results from all feeds in chronological order. Note we can't
        # use yield/return here since there's no incoming message.
        dest = self._get_sender(roomfeed.message)

        formatter = self.entry_format_function()
        for entry in entries:
            self.send(dest, formatter(**entry))

    def _register_roomfeed(self, title: str, check_date: arrow.Arrow, url: str, config, message) -> str:
        """
        :param str title:
            The title of the feed.

        :param arrow.Arrow check_date:
        :param str url:
        :param dict config:
        :param errbot.Message message:
        :return:
        """
        room_id = self._get_room_id(message)

        # Check if the feed is being watched for this room
        if self._is_feed_in_room(title=title, room_id=room_id):
            return f"I am already watching '{title}' for this room."

        # Check if the feed is already in the registry, do it if it's not
        if title not in self.feeds:
            self.add_feed(title, url)

        # add the room to the feed
        self.add_room_to_feed(title=title, message=message, check_date=check_date)

        # Report new feed watch
        self.log.info('Watching {!r} for {!s}'.format(title, message.frm))
        return f'watching [{title}]({url})'

    def _get_first_entry_date(self, entries):
        feed_dates = sorted([read_date(entry.get('published')) for entry in entries])
        return feed_dates[0] if feed_dates else None

    def _feed_reader(self, url: str) -> FeedReader:
        if url not in self._feed_readers:
            config = self._find_url_ini_config(url)
            authenticator = Authenticator(
                url=config['login_url'],
                username=config['username'],
                password=config['password']
            )
            self._feed_readers[url] = FeedReader(
                http_session=self.session,
                authenticator=authenticator,
                logger=self.log
            )
        return self._feed_readers[url]

    def _watch_feed(self, message, url, check_date=None):
        """Watch a new feed by URL and start checking date."""
        feed_reader = self._feed_reader(url)
        feed = feed_reader.read(url=url)
        if feed is None:
            return f"Couldn't find a feed at {url}"

        # get the check date for this new feed
        if check_date is None:
            first_entry_date = self._get_first_entry_date(entries=feed['entries'])
            check_date = first_entry_date if first_entry_date else arrow.now()

        return self._register_roomfeed(
            title=feed['feed']['title'],
            check_date=check_date,
            url=url,
            config=config,
            message=message
        )

    @botcmd
    def rss_list(self, message, args):
        """List the feeds being watched in this room."""
        room_id = self._get_room_id(message)
        room_feeds = [feed for title, feed in self.feeds.items() if feed.isin(room_id)]
        if not room_feeds:
            return 'You have 0 feeds. Add one!'
        for feed in room_feeds:
            last_check = feed.roomfeeds[room_id].last_check.humanize()
            yield f'[{feed.title}]({feed.url}) {last_check}'

    @botcmd
    @arg_botcmd('url', type=str)
    @arg_botcmd('--date', dest='date', type=str, default=None)
    def rss_watchfrom(self, message, url, date=None):
        """Watch a new feed by URL starting from `date`.
        If `date` is None, will use `arrow.now()` as starting date.
        """
        check_date = read_date(date) if date else arrow.now()
        return self._watch_feed(message, url, check_date=check_date)

    @botcmd
    @arg_botcmd('url', type=str)
    def rss_watch(self, message, url):
        """Watch a new feed by URL."""
        return self._watch_feed(message, url, check_date=self.startup_date)

    @botcmd
    @arg_botcmd('url', type=str)
    def rss_ignore(self, message, url):
        """Ignore a currently watched feed by name."""
        for feed in self._get_feeds_from_url(url):
            if feed.isin(message.frm.person):
                try:
                    self.remove_feed_from_room(feed.title, message)
                except Exception as error:
                    self.log.error(
                        f"Error when removing feed [{feed.title}] from room {message.frm.person}. "
                        f"{str(error)}"
                    )
                else:
                    return f"Ignoring [{feed.title}]({feed.url})."
        else:
            return "What feed are you talking bout?"

    @botcmd
    def rss_interval(self, message, interval=None):
        """Get or set the polling interval."""
        if not interval:
            return f'current interval is {self.interval}s'

        try:
            interval = int(interval)
        except ValueError:
            msg = (f"That's not how this works. Give me a number of "
                   f"seconds besides {self.interval} (that's what it is right now).")
            return msg
        else:
            if interval == self.interval:
                return f'the interval is already set to {self.interval}s.'
            else:
                old = self.interval
                self.interval = interval
                return f'changed interval from {old}s to {self.interval}s'
