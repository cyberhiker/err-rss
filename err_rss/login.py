import requests


class Authenticator:
    def __init__(self, url: str, username: str, password: str, login_type='csrf'):
        self.url = url
        self.username = username
        self.password = password
        self.type = login_type

    def login(self, session: requests.Session) -> requests.Session:
        if self.type == 'csrf':
            return self._csrf_login(session)
        else:
            return self._plain_login(session)

    def _plain_login(self, session: requests.Session) -> requests.Session:
        session.auth = self.username, self.password
        return session

    def _csrf_login(self, session: requests.Session) -> requests.Session:
        django_csrf_login(
            session=session,
            login_url=self.url,
            username=self.username,
            password=self.password,
            next_url=self.url
        )
        return session


def django_csrf_login(session, login_url, username, password, next_url=None):
    """ Perform standard authentication with CSRF on a Django application.

    :param session: requests.Session

    :param login_url: str
        The URL where the login is performed.

    :param username: str

    :param password: str

    :param next_url: str, optional
        The URL from where you want to pick information.
        Will return the response from the login_url if None.

    :returns: requests.Response
        The response from the last POST.

    :note: `session` will be modified.
    """
    # authentication
    csrftoken = session.get(login_url).cookies['csrftoken']

    if next_url is None:
        next_url = '/'

    login_data = dict(
        username=username,
        password=password,
        csrfmiddlewaretoken=csrftoken,
        next=next_url
    )

    # get response from next_url
    resp = session.post(
        login_url,
        data=login_data,
        headers=dict(Referer=login_url)
    )
    return resp
