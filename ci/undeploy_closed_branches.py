import sys
import os
import subprocess

prefixes = [
    'notify-f-',
    'notify-api-f-',
    'notify-celery-worker-f-',  # TODO: remove once all cleaned up
    'notify-celery-worker-default-f-',
    'notify-celery-worker-priority-f-',
    'notify-celery-worker-sender-f-',
    'notify-celery-worker-callbacks-f-',
    'notify-celery-worker-retrys-f-',
    'notify-celery-worker-internal-f-',
    'notify-celery-beat-f-',
    'notify-docs-f-',
    'notify-psql-f-',
]

def unprefixed_entity(entities):
    for entity in entities:
        entity = entity.strip()

        for prefix in prefixes:
            if entity.startswith(prefix):
                yield entity.replace(prefix, '', 1)

def feature_branches():
    yield from subprocess.run(
            ['make', '-s', 'list-branches'],
            encoding='utf-8',
            capture_output=True
            ).stdout.splitlines()

def deployed_features():
    yield from subprocess.run(
            ['make', '-s', 'list-apps'],
            encoding='utf-8',
            capture_output=True
            ).stdout.splitlines()

    yield from subprocess.run(
            ['make', '-s', 'list-services'],
            encoding='utf-8',
            capture_output=True
            ).stdout.splitlines()

if __name__ == '__main__':
    deployed = set(unprefixed_entity(deployed_features()))
    branches = set(feature_branches())

    for entity in deployed - branches:
        subprocess.run(['make', 'undeploy-{}'.format(entity)])
