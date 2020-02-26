import os
import importlib
from unittest import mock

import pytest

from app import config
from app.config import QueueNames


def cf_conf():
    os.environ['ADMIN_BASE_URL'] = 'cf'


@pytest.fixture
def reload_config():
    """
    Reset config, by simply re-running config.py from a fresh environment
    """
    old_env = os.environ.copy()

    yield

    os.environ = old_env
    importlib.reload(config)


def test_load_cloudfoundry_config_if_available(monkeypatch, reload_config):
    os.environ['ADMIN_BASE_URL'] = 'env'
    monkeypatch.setenv('VCAP_SERVICES', '{}')
    monkeypatch.setenv('VCAP_APPLICATION', '{}')

    with mock.patch('app.cloudfoundry_config.extract_cloudfoundry_config', side_effect=cf_conf) as cf_config:
        # reload config so that its module level code (ie: all of it) is re-instantiated
        importlib.reload(config)

    assert cf_config.called

    assert os.environ['ADMIN_BASE_URL'] == 'cf'
    assert config.Config.ADMIN_BASE_URL == 'cf'


def test_cloudfoundry_config_has_different_defaults():
    # these should always be set on Sandbox
    assert config.Sandbox.REDIS_ENABLED is False


def test_queue_names_all_queues_correct():
    # Need to ensure that all_queues() only returns queue names used in API
    queues = QueueNames.all_queues()
    assert len(queues) == 13
    assert set([
        QueueNames.PRIORITY,
        QueueNames.PERIODIC,
        QueueNames.DATABASE,
        QueueNames.SEND_SMS,
        QueueNames.SEND_EMAIL,
        QueueNames.RESEARCH_MODE,
        QueueNames.STATISTICS,
        QueueNames.JOBS,
        QueueNames.RETRY,
        QueueNames.NOTIFY,
        QueueNames.CREATE_LETTERS_PDF,
        QueueNames.CALLBACKS,
        QueueNames.LETTERS,
    ]) == set(queues)
