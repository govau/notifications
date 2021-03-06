from app import db
from app.dao.dao_utils import transactional
from app.models import CallbackFailure, Service
from flask import current_app
from sqlalchemy import func, desc
import datetime

SERVICE_STAT_INTERVAL = 'hour'
IS_FAILING_MIN_FAILURES = 50
IS_FAILING_MAX_FAILURES = 500


def service_stats_are_failing(*, failure_count, failing_notification_count):
    if failing_notification_count < IS_FAILING_MIN_FAILURES:
        return False

    if failure_count > IS_FAILING_MAX_FAILURES:
        return True

    return False


@transactional
def dao_create_callback_failure(callback_failure):
    db.session.add(callback_failure)


def dao_get_callback_failures_by_service_id(service_id):
    return CallbackFailure.query.join(CallbackFailure.notification).filter_by(service_id=service_id)


def dao_get_callback_failures_for_all_services(page=1):
    return CallbackFailure.query.order_by(
        desc(CallbackFailure.callback_attempt_started)
    ).paginate(
        page=page,
        per_page=current_app.config['PAGE_SIZE']
    )


def dao_get_failing_callback_summary():
    current_time = datetime.datetime.utcnow()
    cutoff_time = current_time - datetime.timedelta(days=3)

    return db.session.query(
        Service.name.label('service_name'),
        CallbackFailure.service_id.label('service_id'),
        func.count().label('failure_count')
    ).join(
        Service
    ).group_by(
        'service_name',
        'service_id',
    ).filter(CallbackFailure.callback_attempt_started > cutoff_time).all()


def dao_get_callback_failure_service_stats(service_id):
    return db.session.query(
        func.count(CallbackFailure.id.distinct()).label('total_failure_count'),
        func.count(CallbackFailure.notification_id.distinct()).label('failed_notification_count'),
    ).select_from(
        CallbackFailure
    ).filter(
        CallbackFailure.service_id == service_id,
    )


def dao_get_callback_failure_service_stats_at_time(service_id, current_time):
    created_started = func.date_trunc(SERVICE_STAT_INTERVAL, CallbackFailure.callback_attempt_started)
    current_started = func.date_trunc(SERVICE_STAT_INTERVAL, current_time)
    return dao_get_callback_failure_service_stats(service_id).filter(created_started == current_started)


def dao_service_callbacks_are_failing(service_id):
    failure_stats = dao_get_callback_failure_service_stats_at_time(service_id, datetime.datetime.utcnow()).first()

    if not failure_stats:
        return False

    return service_stats_are_failing(
        failure_count=failure_stats.total_failure_count,
        failing_notification_count=failure_stats.failed_notification_count,
    )


def dao_get_callback_failing_stats_for_service(service_id):
    return dao_get_callback_failure_service_stats_at_time(service_id, datetime.datetime.utcnow()).first()


def dao_get_callback_failing_stats_for_all_services():
    current_time = datetime.datetime.utcnow()
    cutoff_time = current_time - datetime.timedelta(days=3)

    return db.session.query(
        func.count(CallbackFailure.id.distinct()).label('total_failure_count'),
        func.count(CallbackFailure.notification_id.distinct()).label('failed_notification_count'),
    ).select_from(
        CallbackFailure
    ).filter(CallbackFailure.callback_attempt_started > cutoff_time).first()
