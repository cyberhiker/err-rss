import os

#: Path to ini file for containing username and password by wildcard domain.
CNFG_DIR = os.environ.get('ERRBOT_CFG_DIR', '/etc/errbot')

CONFIG_FILEPATH_CHOICES = [
    os.path.join(os.path.dirname(os.path.dirname(__file__)), 'err-rss.ini'),
    os.path.expanduser('~/.err-rss/config.ini'),
    os.path.join(CNFG_DIR, 'plugins', 'err-rss.ini'),
    os.path.join(CNFG_DIR, 'plugins', 'err-rss', 'err-rss.ini'),
    os.path.join(CNFG_DIR, 'plugins', 'err-rss', 'config.ini'),
]

DEFAULT_CONFIG = {
    'START_DATE': '01/01/2017',  # format: DD/MM/YYYY
    'INTERVAL': 5*60,  # refresh time in seconds#
}


def get_config_filepath():
    for f in CONFIG_FILEPATH_CHOICES:
        if os.path.exists(f):
            return f
