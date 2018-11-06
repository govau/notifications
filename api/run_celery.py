#!/usr/bin/env python

import os
from flask import Flask
import sentry_sdk
from sentry_sdk.integrations.flask import FlaskIntegration

# notify_celery is referenced from manifest_delivery_base.yml, and cannot be removed
from app import notify_celery, create_app  # noqa

sentry_sdk.init(
    dsn=os.getenv("API_SENTRY_DSN"),
    environment=os.getenv("API_SENTRY_ENV"),
    integrations=[FlaskIntegration()]
)

with sentry_sdk.configure_scope() as scope:
    scope.set_tag("celery_cmd", os.environ['NOTIFY_CELERY_CMD'])

application = Flask('delivery')
create_app(application)
application.app_context().push()
