import uuid
from datetime import datetime, timedelta

from flask import current_app
from notifications_utils.statsd_decorators import statsd
from sqlalchemy import (
    Date as sql_date,
    asc,
    cast,
    desc,
    func,
)

from app import db
from app.dao import days_ago
from app.models import (
    Job,
    JOB_STATUS_PENDING,
    JOB_STATUS_SCHEDULED,
    LETTER_TYPE,
    NotificationHistory,
    Template,
)
from app.variables import LETTER_TEST_API_FILENAME


@statsd(namespace="dao")
def dao_get_notification_outcomes_for_job(service_id, job_id):
    query = db.session.query(
        func.count(NotificationHistory.status).label('count'),
        NotificationHistory.status
    )

    return query.filter(
        NotificationHistory.service_id == service_id
    ).filter(
        NotificationHistory.job_id == job_id
    ).group_by(
        NotificationHistory.status
    ).order_by(
        asc(NotificationHistory.status)
    ).all()


def dao_get_job_by_service_id_and_job_id(service_id, job_id):
    return Job.query.filter_by(service_id=service_id, id=job_id).one()


def dao_get_jobs_by_service_id(service_id, limit_days=None, page=1, page_size=50, statuses=None):
    query_filter = [
        Job.service_id == service_id,
        Job.original_file_name != current_app.config['TEST_MESSAGE_FILENAME'],
        Job.original_file_name != current_app.config['ONE_OFF_MESSAGE_FILENAME'],
    ]
    if limit_days is not None:
        query_filter.append(cast(Job.created_at, sql_date) >= days_ago(limit_days))
    if statuses is not None and statuses != ['']:
        query_filter.append(
            Job.job_status.in_(statuses)
        )
    return Job.query \
        .filter(*query_filter) \
        .order_by(Job.processing_started.desc(), Job.created_at.desc()) \
        .paginate(page=page, per_page=page_size)


def dao_get_job_by_id(job_id):
    return Job.query.filter_by(id=job_id).one()


def dao_set_scheduled_jobs_to_pending():
    """
    Sets all past scheduled jobs to pending, and then returns them for further processing.

    this is used in the run_scheduled_jobs task, so we put a FOR UPDATE lock on the job table for the duration of
    the transaction so that if the task is run more than once concurrently, one task will block the other select
    from completing until it commits.
    """
    jobs = Job.query \
        .filter(
            Job.job_status == JOB_STATUS_SCHEDULED,
            Job.scheduled_for < datetime.utcnow()
        ) \
        .order_by(asc(Job.scheduled_for)) \
        .with_for_update() \
        .all()

    for job in jobs:
        job.job_status = JOB_STATUS_PENDING

    db.session.add_all(jobs)
    db.session.commit()

    return jobs


def dao_get_future_scheduled_job_by_id_and_service_id(job_id, service_id):
    return Job.query \
        .filter(
            Job.service_id == service_id,
            Job.id == job_id,
            Job.job_status == JOB_STATUS_SCHEDULED,
            Job.scheduled_for > datetime.utcnow()
        ) \
        .one()


def dao_create_job(job):
    if not job.id:
        job.id = uuid.uuid4()
    db.session.add(job)
    db.session.commit()


def dao_update_job(job):
    db.session.add(job)
    db.session.commit()


def dao_update_job_status(job_id, status):
    db.session.query(Job).filter_by(id=job_id).update({'job_status': status})
    db.session.commit()


def dao_get_jobs_older_than_limited_by(job_types, older_than=7, limit_days=2):
    end_date = datetime.utcnow() - timedelta(days=older_than)
    start_date = end_date - timedelta(days=limit_days)

    return Job.query.join(Template).filter(
        Job.created_at < end_date,
        Job.created_at >= start_date,
        Template.template_type.in_(job_types)
    ).order_by(desc(Job.created_at)).all()


def dao_get_all_letter_jobs():
    return db.session.query(
        Job
    ).join(
        Job.template
    ).filter(
        Template.template_type == LETTER_TYPE,
        # test letter jobs (or from research mode services) are created with a different filename,
        # exclude them so we don't see them on the send to CSV
        Job.original_file_name != LETTER_TEST_API_FILENAME
    ).order_by(
        desc(Job.created_at)
    ).all()


def dao_get_letter_job_ids_by_status(status):
    jobs = db.session.query(
        Job
    ).join(
        Job.template
    ).filter(
        Job.job_status == status,
        Template.template_type == LETTER_TYPE,
        # test letter jobs (or from research mode services) are created with a different filename,
        # exclude them so we don't see them on the send to CSV
        Job.original_file_name != LETTER_TEST_API_FILENAME
    ).order_by(
        desc(Job.created_at)
    ).all()

    return [str(job.id) for job in jobs]
