import os

if os.environ.get('VCAP_APPLICATION'):
    pass


class Config(object):
    ADMIN_CLIENT_SECRET = os.environ.get('ADMIN_CLIENT_SECRET')
    API_HOST_NAME = os.environ.get('API_HOST_NAME')
    SECRET_KEY = os.environ.get('SECRET_KEY')
    DANGEROUS_SALT = os.environ.get('DANGEROUS_SALT')
    DESKPRO_API_HOST = os.environ.get('DESKPRO_API_HOST')
    DESKPRO_API_KEY = os.environ.get('DESKPRO_API_KEY')

    ADMIN_SENTRY_ENV = os.environ.get('ADMIN_SENTRY_ENV')
    ADMIN_SENTRY_DSN = os.environ.get('ADMIN_SENTRY_DSN')

    DEFAULT_TIMEZONE = 'Australia/Sydney'

    # if we're not on cloudfoundry, we can get to this app from localhost. but on cloudfoundry its different
    ADMIN_BASE_URL = os.environ.get('ADMIN_BASE_URL', 'http://localhost:6012')

    CDN_BASE_URL = os.environ.get('CDN_BASE_URL', 'https://notify-static-logos-staging.static.cld.gov.au')
    DOCS_BASE_URL = os.environ.get('DOCS_BASE_URL', 'https://docs.notify.gov.au')

    TEMPLATE_PREVIEW_API_HOST = os.environ.get('TEMPLATE_PREVIEW_API_HOST', 'http://localhost:6013')
    TEMPLATE_PREVIEW_API_KEY = os.environ.get('TEMPLATE_PREVIEW_API_KEY', 'my-secret-key')

    # Hosted graphite statsd prefix
    STATSD_PREFIX = os.getenv('STATSD_PREFIX')

    # Email reverification
    DAYS_BETWEEN_EMAIL_REVERIFICATIONS = 30
    FEATURE_EMAIL_REVERIFICATION_ENABLED = True

    # Logging
    DEBUG = False
    NOTIFY_LOG_PATH = os.getenv('NOTIFY_LOG_PATH')

    # Password rotation
    DAYS_BETWEEN_PASSWORD_ROTATIONS = 365
    FEATURE_PASSWORD_ROTATION_ENABLED = True

    CSV_UPLOAD_BUCKET_NAME = os.getenv('CSV_UPLOAD_BUCKET_NAME', 'dta-notify-csv-upload-20180712070203208700000001')
    LOGO_UPLOAD_BUCKET_NAME = os.getenv('LOGO_UPLOAD_BUCKET_NAME', 'public_logos-local')

    DESKPRO_DEPT_ID = 5
    DESKPRO_ASSIGNED_AGENT_TEAM_ID = 5

    ADMIN_CLIENT_USER_NAME = 'notify-admin'
    ASSETS_DEBUG = False

    AWS_REGION = os.getenv('AWS_REGION', 'ap-southeast-2')
    AWS_LOGO_ACCESS_KEY_ID = os.getenv('AWS_LOGO_ACCESS_KEY_ID')
    AWS_LOGO_SECRET_ACCESS_KEY = os.getenv('AWS_LOGO_SECRET_ACCESS_KEY')

    DEFAULT_SERVICE_LIMIT = 50
    DEFAULT_FREE_SMS_FRAGMENT_LIMITS = {
        'central': 25000,
        'local': 25000,
        'nhs': 25000,
        'federal': 25000,
        'state': 25000,
    }
    EMAIL_EXPIRY_SECONDS = 3600  # 1 hour
    INVITATION_EXPIRY_SECONDS = 3600 * 24 * 2  # 2 days - also set on api
    EMAIL_2FA_EXPIRY_SECONDS = 1800  # 30 Minutes
    HEADER_COLOUR = '#9263de'  # DTA design system purple
    HTTP_PROTOCOL = 'http'
    MAX_FAILED_LOGIN_COUNT = 5
    MAX_FAILED_VERIFY_COUNT = 5
    NOTIFY_APP_NAME = 'admin'
    NOTIFY_LOG_LEVEL = 'DEBUG'
    PERMANENT_SESSION_LIFETIME = 8 * 60 * 60  # 8 hours
    SEND_FILE_MAX_AGE_DEFAULT = 365 * 24 * 60 * 60  # 1 year
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_NAME = 'notify_admin_session'
    SESSION_COOKIE_SECURE = True
    SESSION_REFRESH_EACH_REQUEST = True
    SHOW_STYLEGUIDE = True
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = None

    DESKPRO_PERSON_EMAIL = 'donotreply@notifications.service.gov.uk'
    ACTIVITY_STATS_LIMIT_DAYS = 7
    TEST_MESSAGE_FILENAME = 'Report'

    STATSD_ENABLED = False
    STATSD_HOST = "statsd.hostedgraphite.com"
    STATSD_PORT = 8125
    NOTIFY_ENVIRONMENT = 'development'
    MOU_BUCKET_NAME = 'local-mou'
    ROUTE_SECRET_KEY_1 = os.environ.get('ROUTE_SECRET_KEY_1', '')
    ROUTE_SECRET_KEY_2 = os.environ.get('ROUTE_SECRET_KEY_2', '')
    CHECK_PROXY_HEADER = False


class Development(Config):
    NOTIFY_LOG_PATH = 'application.log'
    DEBUG = True
    SESSION_COOKIE_SECURE = False
    SESSION_PROTECTION = None
    STATSD_ENABLED = False
    MOU_BUCKET_NAME = 'notify.tools-mou'

    ADMIN_CLIENT_SECRET = 'dev-notify-secret-key'
    API_HOST_NAME = 'http://localhost:6011'
    DANGEROUS_SALT = 'dev-notify-salt'
    SECRET_KEY = 'dev-notify-secret-key'
    DESKPRO_API_HOST = "some-host"
    DESKPRO_API_KEY = "some-key"


class Test(Development):
    DEBUG = True
    TESTING = True
    STATSD_ENABLED = False
    WTF_CSRF_ENABLED = False
    MOU_BUCKET_NAME = 'test-mou'
    NOTIFY_ENVIRONMENT = 'test'
    API_HOST_NAME = 'http://you-forgot-to-mock-an-api-call-to'
    TEMPLATE_PREVIEW_API_HOST = 'http://localhost:9999'


class Preview(Config):
    HTTP_PROTOCOL = 'https'
    HEADER_COLOUR = '#F499BE'  # $baby-pink
    STATSD_ENABLED = False
    MOU_BUCKET_NAME = 'notify.works-mou'
    NOTIFY_ENVIRONMENT = 'preview'
    CHECK_PROXY_HEADER = True


class Staging(Config):
    SHOW_STYLEGUIDE = False
    HTTP_PROTOCOL = 'https'
    HEADER_COLOUR = '#6F72AF'  # $mauve
    STATSD_ENABLED = False
    MOU_BUCKET_NAME = 'staging-notify.works-mou'
    NOTIFY_ENVIRONMENT = 'staging'
    CHECK_PROXY_HEADER = True


class Live(Config):
    SHOW_STYLEGUIDE = False
    HEADER_COLOUR = '#313131'  # DTA dark gray
    HTTP_PROTOCOL = 'https'
    STATSD_ENABLED = False
    MOU_BUCKET_NAME = 'notifications.service.gov.uk-mou'
    NOTIFY_ENVIRONMENT = 'live'
    CHECK_PROXY_HEADER = False


class CloudFoundryConfig(Config):
    pass


# CloudFoundry sandbox
class Sandbox(CloudFoundryConfig):
    HTTP_PROTOCOL = 'https'
    HEADER_COLOUR = '#F499BE'  # $baby-pink
    STATSD_ENABLED = False
    NOTIFY_ENVIRONMENT = 'sandbox'


configs = {
    'development': Development,
    'test': Test,
    'preview': Preview,
    'staging': Staging,
    'live': Live,
    'production': Live,
    'sandbox': Sandbox
}
