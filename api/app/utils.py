from datetime import datetime, timedelta

import pytz
from flask import url_for
from sqlalchemy import func
from notifications_utils.template import SMSMessageTemplate, PlainTextEmailTemplate

# AET is Australian Eastern Time (https://www.timeanddate.com/time/zones/aet).
aet_tz_str = "Australia/Sydney"
aet_tz = pytz.timezone(aet_tz_str)


def pagination_links(pagination, endpoint, **kwargs):
    if 'page' in kwargs:
        kwargs.pop('page', None)
    links = {}
    if pagination.has_prev:
        links['prev'] = url_for(endpoint, page=pagination.prev_num, **kwargs)
    if pagination.has_next:
        links['next'] = url_for(endpoint, page=pagination.next_num, **kwargs)
        links['last'] = url_for(endpoint, page=pagination.pages, **kwargs)
    return links


def url_with_token(data, url, config, base_url=None):
    from notifications_utils.url_safe_token import generate_token
    token = generate_token(data, config['SECRET_KEY'], config['DANGEROUS_SALT'])
    base_url = (base_url or config['ADMIN_BASE_URL']) + url
    return base_url + token


def get_template_instance(template, values):
    from app.models import SMS_TYPE, EMAIL_TYPE, LETTER_TYPE
    return {
        SMS_TYPE: SMSMessageTemplate, EMAIL_TYPE: PlainTextEmailTemplate, LETTER_TYPE: PlainTextEmailTemplate
    }[template['template_type']](template, values)


def get_sydney_midnight_in_utc(date):
    """
     This function takes in a local date, converts it to midnight (sets time to
     00:00), then localizes to aet_tz. Finally, it converts it to UTC.
     It drops the timezone information information because the database stores
     the timestamps without timezone.
     :param date: a localized datetime for which to calculate the Sydney midnight in UTC
     :return: the UTC datetime of Sydney midnight, for example 2016-11-26 = 2016-11-25 13:00:00 (13:00, not 14:00 because this date is during AEDT)
    """
    return aet_tz.localize(datetime.combine(date, datetime.min.time())).astimezone(
        pytz.UTC).replace(
        tzinfo=None)


def get_midnight_for_day_before(date):
    day_before = date - timedelta(1)
    return get_sydney_midnight_in_utc(day_before)


def convert_utc_to_local(utc_dt, local_tz):
    return pytz.utc.localize(utc_dt).astimezone(local_tz).replace(tzinfo=None)


def convert_utc_to_aet(utc_dt):
    return convert_utc_to_local(utc_dt, aet_tz)


def convert_local_to_utc(date, local_tz):
    return local_tz.localize(date).astimezone(pytz.UTC).replace(tzinfo=None)


def convert_aet_to_utc(date):
    return convert_local_to_utc(date, aet_tz)


def get_sydney_month_from_utc_column(column):
    """
     Where queries need to count notifications by month it needs to be
     the month in AET.
     The database stores all timestamps as UTC without the timezone.
      - First set the timezone on created_at to UTC
      - then convert the timezone to AET
      - lastly truncate the datetime to month with which we can group
        queries
    """
    return func.date_trunc(
        "month",
        func.timezone(aet_tz_str, func.timezone("UTC", column))
    )


def cache_key_for_service_template_counter(service_id, limit_days=7):
    return "{}-template-counter-limit-{}-days".format(service_id, limit_days)


def get_public_notify_type_text(notify_type, plural=False):
    from app.models import SMS_TYPE
    notify_type_text = notify_type
    if notify_type == SMS_TYPE:
        notify_type_text = 'text message'

    return '{}{}'.format(notify_type_text, 's' if plural else '')


def midnight_n_days_ago(number_of_days):
    """
    Returns midnight a number of days ago (in UTC). Takes care of daylight savings etc.
    """
    return get_sydney_midnight_in_utc(datetime.utcnow() - timedelta(days=number_of_days))


def escape_special_characters(string):
    for special_character in ('\\', '_', '%', '/'):
        string = string.replace(
            special_character,
            r'\{}'.format(special_character)
        )
    return string
