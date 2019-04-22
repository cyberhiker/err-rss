
class RoomFeed(object):
    """ Store the room ID, the message used to launch the feed
    and the last time the feed was checked.
    """
    def __init__(self, room_id, message, last_check):
        self.room_id = room_id
        self.message = message
        self.last_check = last_check


class Feed(object):
    """ Store the title of the feed and its the URL.
    Also a RoomFeed dict, where the key is the room_id.
    """

    def __init__(self, title, url):
        self.title = title
        self.url = url
        self.roomfeeds = {}

    def add_room(self, room_id, message, last_check):
        """ Add a RoomFeed to the roomfeeds.

        :param room_id: str or int
        :param message:
        :param last_check: arrow.Arrow
        :return:
        """
        if room_id in self.roomfeeds:
            raise KeyError(f'The room {room_id} is already registered for this feed.')

        self.roomfeeds[room_id] = RoomFeed(
            room_id=room_id,
            message=message,
            last_check=last_check
        )

    def remove_room(self, room_id):
        del self.roomfeeds[room_id]

    def isin(self, room_id):
        return room_id in self.roomfeeds

    def has_rooms(self):
        return bool(self.roomfeeds)
