from datetime import datetime, timedelta
from functools import partial
import pytest
import uuid

from freezegun import freeze_time

from app.dao.jobs_dao import (
    dao_get_job_by_service_id_and_job_id,
    dao_create_job,
    dao_update_job,
    dao_get_jobs_by_service_id,
    dao_set_scheduled_jobs_to_pending,
    dao_get_future_scheduled_job_by_id_and_service_id,
    dao_get_notification_outcomes_for_job,
    dao_update_job_status,
    dao_get_jobs_older_than_limited_by,
    dao_get_letter_job_ids_by_status)
from app.models import (
    Job,
    EMAIL_TYPE, SMS_TYPE, LETTER_TYPE,
    JOB_STATUS_READY_TO_SEND, JOB_STATUS_SENT_TO_DVLA, JOB_STATUS_FINISHED, JOB_STATUS_PENDING
)

from tests.app.conftest import sample_notification as create_notification
from tests.app.conftest import sample_job as create_job
from tests.app.conftest import sample_service as create_service
from tests.app.conftest import sample_template as create_template
from tests.app.db import (
    create_user,
    create_job as create_db_job,
    create_service as create_db_service,
    create_template as create_db_template
)


def test_should_have_decorated_notifications_dao_functions():
    assert dao_get_notification_outcomes_for_job.__wrapped__.__name__ == 'dao_get_notification_outcomes_for_job'  # noqa


def test_should_get_all_statuses_for_notifications_associated_with_job(
        notify_db,
        notify_db_session,
        sample_service,
        sample_job
):
    notification = partial(create_notification, notify_db, notify_db_session, service=sample_service, job=sample_job)
    notification(status='created')
    notification(status='sending')
    notification(status='delivered')
    notification(status='pending')
    notification(status='failed')
    notification(status='technical-failure')
    notification(status='temporary-failure')
    notification(status='permanent-failure')
    notification(status='sent')

    results = dao_get_notification_outcomes_for_job(sample_service.id, sample_job.id)
    assert set([(row.count, row.status) for row in results]) == set([
        (1, 'created'),
        (1, 'sending'),
        (1, 'delivered'),
        (1, 'pending'),
        (1, 'failed'),
        (1, 'technical-failure'),
        (1, 'temporary-failure'),
        (1, 'permanent-failure'),
        (1, 'sent')
    ])


def test_should_count_of_statuses_for_notifications_associated_with_job(
        notify_db,
        notify_db_session,
        sample_service,
        sample_job
):
    notification = partial(create_notification, notify_db, notify_db_session, service=sample_service, job=sample_job)
    notification(status='created')
    notification(status='created')

    notification(status='sending')
    notification(status='sending')
    notification(status='sending')
    notification(status='sending')
    notification(status='delivered')
    notification(status='delivered')

    results = dao_get_notification_outcomes_for_job(sample_service.id, sample_job.id)
    assert set([(row.count, row.status) for row in results]) == set([
        (2, 'created'),
        (4, 'sending'),
        (2, 'delivered')
    ])


def test_should_return_zero_length_array_if_no_notifications_for_job(sample_service, sample_job):
    assert len(dao_get_notification_outcomes_for_job(sample_job.id, sample_service.id)) == 0


def test_should_return_notifications_only_for_this_job(notify_db, notify_db_session, sample_service):
    job_1 = create_job(notify_db, notify_db_session, service=sample_service)
    job_2 = create_job(notify_db, notify_db_session, service=sample_service)

    create_notification(notify_db, notify_db_session, service=sample_service, job=job_1, status='created')
    create_notification(notify_db, notify_db_session, service=sample_service, job=job_2, status='created')

    results = dao_get_notification_outcomes_for_job(sample_service.id, job_1.id)
    assert [(row.count, row.status) for row in results] == [
        (1, 'created')
    ]


def test_should_return_notifications_only_for_this_service(notify_db, notify_db_session):
    service_1 = create_service(notify_db, notify_db_session, service_name="one", email_from="one")
    service_2 = create_service(notify_db, notify_db_session, service_name="two", email_from="two")

    job_1 = create_job(notify_db, notify_db_session, service=service_1)
    job_2 = create_job(notify_db, notify_db_session, service=service_2)

    create_notification(notify_db, notify_db_session, service=service_1, job=job_1, status='created')
    create_notification(notify_db, notify_db_session, service=service_2, job=job_2, status='created')

    assert len(dao_get_notification_outcomes_for_job(service_1.id, job_2.id)) == 0


def test_create_job(sample_template):
    assert Job.query.count() == 0

    job_id = uuid.uuid4()
    data = {
        'id': job_id,
        'service_id': sample_template.service.id,
        'template_id': sample_template.id,
        'template_version': sample_template.version,
        'original_file_name': 'some.csv',
        'notification_count': 1,
        'created_by': sample_template.created_by
    }

    job = Job(**data)
    dao_create_job(job)

    assert Job.query.count() == 1
    job_from_db = Job.query.get(job_id)
    assert job == job_from_db
    assert job_from_db.notifications_delivered == 0
    assert job_from_db.notifications_failed == 0


def test_get_job_by_id(sample_job):
    job_from_db = dao_get_job_by_service_id_and_job_id(sample_job.service.id, sample_job.id)
    assert sample_job == job_from_db


def test_get_jobs_for_service(notify_db, notify_db_session, sample_template):
    one_job = create_job(notify_db, notify_db_session, sample_template.service, sample_template)

    other_user = create_user(email="test@digital.cabinet-office.gov.uk")
    other_service = create_service(notify_db, notify_db_session, user=other_user, service_name="other service",
                                   email_from='other.service')
    other_template = create_template(notify_db, notify_db_session, service=other_service)
    other_job = create_job(notify_db, notify_db_session, service=other_service, template=other_template)

    one_job_from_db = dao_get_jobs_by_service_id(one_job.service_id).items
    other_job_from_db = dao_get_jobs_by_service_id(other_job.service_id).items

    assert len(one_job_from_db) == 1
    assert one_job == one_job_from_db[0]

    assert len(other_job_from_db) == 1
    assert other_job == other_job_from_db[0]

    assert one_job_from_db != other_job_from_db


def test_get_jobs_for_service_with_limit_days_param(notify_db, notify_db_session, sample_template):
    one_job = create_job(notify_db, notify_db_session, sample_template.service, sample_template)
    old_job = create_job(notify_db, notify_db_session, sample_template.service, sample_template,
                         created_at=datetime.now() - timedelta(days=8))

    jobs = dao_get_jobs_by_service_id(one_job.service_id).items

    assert len(jobs) == 2
    assert one_job in jobs
    assert old_job in jobs

    jobs_limit_days = dao_get_jobs_by_service_id(one_job.service_id, limit_days=7).items
    assert len(jobs_limit_days) == 1
    assert one_job in jobs_limit_days
    assert old_job not in jobs_limit_days


def test_get_jobs_for_service_with_limit_days_edge_case(notify_db, notify_db_session, sample_template):
    one_job = create_job(notify_db, notify_db_session, sample_template.service, sample_template)
    job_two = create_job(notify_db, notify_db_session, sample_template.service, sample_template,
                         created_at=(datetime.now() - timedelta(days=7)).date())
    one_second_after_midnight = datetime.combine((datetime.now() - timedelta(days=7)).date(),
                                                 datetime.strptime("000001", "%H%M%S").time())
    just_after_midnight_job = create_job(notify_db, notify_db_session, sample_template.service, sample_template,
                                         created_at=one_second_after_midnight)
    job_eight_days_old = create_job(notify_db, notify_db_session, sample_template.service, sample_template,
                                    created_at=datetime.now() - timedelta(days=8))

    jobs_limit_days = dao_get_jobs_by_service_id(one_job.service_id, limit_days=7).items
    assert len(jobs_limit_days) == 3
    assert one_job in jobs_limit_days
    assert job_two in jobs_limit_days
    assert just_after_midnight_job in jobs_limit_days
    assert job_eight_days_old not in jobs_limit_days


def test_get_jobs_for_service_in_processed_at_then_created_at_order(notify_db, notify_db_session, sample_template):

    _create_job = partial(create_job, notify_db, notify_db_session, sample_template.service, sample_template)
    from_hour = partial(datetime, 2001, 1, 1)

    created_jobs = [
        _create_job(created_at=from_hour(2), processing_started=None),
        _create_job(created_at=from_hour(1), processing_started=None),
        _create_job(created_at=from_hour(1), processing_started=from_hour(4)),
        _create_job(created_at=from_hour(2), processing_started=from_hour(3)),
    ]

    jobs = dao_get_jobs_by_service_id(sample_template.service.id).items

    assert len(jobs) == len(created_jobs)

    for index in range(0, len(created_jobs)):
        assert jobs[index].id == created_jobs[index].id


def test_update_job(sample_job):
    assert sample_job.job_status == 'pending'

    sample_job.job_status = 'in progress'

    dao_update_job(sample_job)

    job_from_db = Job.query.get(sample_job.id)

    assert job_from_db.job_status == 'in progress'


def test_set_scheduled_jobs_to_pending_gets_all_jobs_in_scheduled_state_before_now(notify_db, notify_db_session):
    one_minute_ago = datetime.utcnow() - timedelta(minutes=1)
    one_hour_ago = datetime.utcnow() - timedelta(minutes=60)
    job_new = create_job(notify_db, notify_db_session, scheduled_for=one_minute_ago, job_status='scheduled')
    job_old = create_job(notify_db, notify_db_session, scheduled_for=one_hour_ago, job_status='scheduled')
    jobs = dao_set_scheduled_jobs_to_pending()
    assert len(jobs) == 2
    assert jobs[0].id == job_old.id
    assert jobs[1].id == job_new.id


def test_set_scheduled_jobs_to_pending_gets_ignores_jobs_not_scheduled(notify_db, notify_db_session):
    one_minute_ago = datetime.utcnow() - timedelta(minutes=1)
    create_job(notify_db, notify_db_session)
    job_scheduled = create_job(notify_db, notify_db_session, scheduled_for=one_minute_ago, job_status='scheduled')
    jobs = dao_set_scheduled_jobs_to_pending()
    assert len(jobs) == 1
    assert jobs[0].id == job_scheduled.id


def test_set_scheduled_jobs_to_pending_gets_ignores_jobs_scheduled_in_the_future(sample_scheduled_job):
    jobs = dao_set_scheduled_jobs_to_pending()
    assert len(jobs) == 0


def test_set_scheduled_jobs_to_pending_updates_rows(notify_db, notify_db_session):
    one_minute_ago = datetime.utcnow() - timedelta(minutes=1)
    one_hour_ago = datetime.utcnow() - timedelta(minutes=60)
    create_job(notify_db, notify_db_session, scheduled_for=one_minute_ago, job_status='scheduled')
    create_job(notify_db, notify_db_session, scheduled_for=one_hour_ago, job_status='scheduled')
    jobs = dao_set_scheduled_jobs_to_pending()
    assert len(jobs) == 2
    assert jobs[0].job_status == 'pending'
    assert jobs[1].job_status == 'pending'


def test_get_future_scheduled_job_gets_a_job_yet_to_send(sample_scheduled_job):
    result = dao_get_future_scheduled_job_by_id_and_service_id(sample_scheduled_job.id, sample_scheduled_job.service_id)
    assert result.id == sample_scheduled_job.id


@freeze_time('2016-10-31 10:00:00')
def test_should_get_jobs_seven_days_old(notify_db, notify_db_session, sample_template):
    """
    Jobs older than seven days are deleted, but only two day's worth (two-day window)
    """
    seven_days_ago = datetime.utcnow() - timedelta(days=7)
    within_seven_days = seven_days_ago + timedelta(seconds=1)

    eight_days_ago = seven_days_ago - timedelta(days=1)

    nine_days_ago = eight_days_ago - timedelta(days=2)
    nine_days_one_second_ago = nine_days_ago - timedelta(seconds=1)

    job = partial(create_job, notify_db, notify_db_session)
    job(created_at=seven_days_ago)
    job(created_at=within_seven_days)
    job_to_delete = job(created_at=eight_days_ago)
    job(created_at=nine_days_ago)
    job(created_at=nine_days_one_second_ago)

    jobs = dao_get_jobs_older_than_limited_by(job_types=[sample_template.template_type])

    assert len(jobs) == 1
    assert jobs[0].id == job_to_delete.id


def test_get_jobs_for_service_is_paginated(notify_db, notify_db_session, sample_service, sample_template):
    with freeze_time('2015-01-01T00:00:00') as the_time:
        for _ in range(10):
            the_time.tick(timedelta(hours=1))
            create_job(notify_db, notify_db_session, sample_service, sample_template)

    res = dao_get_jobs_by_service_id(sample_service.id, page=1, page_size=2)

    assert res.per_page == 2
    assert res.total == 10
    assert len(res.items) == 2
    assert res.items[0].created_at == datetime(2015, 1, 1, 10)
    assert res.items[1].created_at == datetime(2015, 1, 1, 9)

    res = dao_get_jobs_by_service_id(sample_service.id, page=2, page_size=2)

    assert len(res.items) == 2
    assert res.items[0].created_at == datetime(2015, 1, 1, 8)
    assert res.items[1].created_at == datetime(2015, 1, 1, 7)


@pytest.mark.parametrize('file_name', [
    'Test message',
    'Report',
])
def test_get_jobs_for_service_doesnt_return_test_messages(
    notify_db,
    notify_db_session,
    sample_template,
    sample_job,
    file_name,
):
    create_job(
        notify_db,
        notify_db_session,
        sample_template.service,
        sample_template,
        original_file_name=file_name,
    )

    jobs = dao_get_jobs_by_service_id(sample_job.service_id).items

    assert jobs == [sample_job]


def test_dao_update_job_status(sample_job):
    dao_update_job_status(sample_job.id, 'sent to dvla')
    updated_job = Job.query.get(sample_job.id)
    assert updated_job.job_status == 'sent to dvla'
    assert updated_job.updated_at


@freeze_time('2016-10-31 10:00:00')
def test_should_get_jobs_seven_days_old_filters_type(notify_db, notify_db_session):
    eight_days_ago = datetime.utcnow() - timedelta(days=8)
    letter_template = create_template(notify_db, notify_db_session, template_type=LETTER_TYPE)
    sms_template = create_template(notify_db, notify_db_session, template_type=SMS_TYPE)
    email_template = create_template(notify_db, notify_db_session, template_type=EMAIL_TYPE)

    job = partial(create_job, notify_db, notify_db_session, created_at=eight_days_ago)
    job_to_remain = job(template=letter_template)
    job(template=sms_template)
    job(template=email_template)

    jobs = dao_get_jobs_older_than_limited_by(
        job_types=[EMAIL_TYPE, SMS_TYPE]
    )

    assert len(jobs) == 2
    assert job_to_remain.id not in [job.id for job in jobs]


def assert_job_stat(job, result, sent, delivered, failed):
    assert result.job_id == job.id
    assert result.original_file_name == job.original_file_name
    assert result.created_at == job.created_at
    assert result.scheduled_for == job.scheduled_for
    assert result.template_id == job.template_id
    assert result.template_version == job.template_version
    assert result.job_status == job.job_status
    assert result.service_id == job.service_id
    assert result.notification_count == job.notification_count
    assert result.sent == sent
    assert result.delivered == delivered
    assert result.failed == failed


def test_dao_get_letter_job_ids_by_status(sample_service):
    another_service = create_db_service(service_name="another service")

    sms_template = create_db_template(service=sample_service, template_type=SMS_TYPE)
    email_template = create_db_template(service=sample_service, template_type=EMAIL_TYPE)
    letter_template_1 = create_db_template(service=sample_service, template_type=LETTER_TYPE)
    letter_template_2 = create_db_template(service=another_service, template_type=LETTER_TYPE)
    letter_job_1 = create_db_job(letter_template_1, job_status=JOB_STATUS_READY_TO_SEND, original_file_name='1.csv')
    letter_job_2 = create_db_job(letter_template_2, job_status=JOB_STATUS_READY_TO_SEND, original_file_name='2.csv')
    ready_letter_job_ids = [str(letter_job_1.id), str(letter_job_2.id)]

    create_db_job(sms_template, job_status=JOB_STATUS_FINISHED)
    create_db_job(email_template, job_status=JOB_STATUS_FINISHED)
    create_db_job(letter_template_1, job_status=JOB_STATUS_SENT_TO_DVLA)
    create_db_job(letter_template_1, job_status=JOB_STATUS_FINISHED)
    create_db_job(letter_template_2, job_status=JOB_STATUS_PENDING)

    result = dao_get_letter_job_ids_by_status(JOB_STATUS_READY_TO_SEND)

    assert len(result) == 2
    assert set(result) == set(ready_letter_job_ids)
