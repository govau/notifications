from datetime import datetime, timedelta, date
import uuid

import pytest

from freezegun import freeze_time
from sqlalchemy.exc import SQLAlchemyError, IntegrityError

from app import db

from app.models import (
    Notification,
    Job,
    NotificationStatistics,
    TemplateStatistics
)

from app.dao.notifications_dao import (
    dao_create_notification,
    dao_update_notification,
    get_notification,
    get_notification_for_job,
    get_notifications_for_job,
    dao_get_notification_statistics_for_service,
    delete_notifications_created_more_than_a_week_ago,
    dao_get_notification_statistics_for_service_and_day,
    update_notification_status_by_id,
    update_notification_reference_by_id,
    update_notification_status_by_reference,
    dao_get_template_statistics_for_service,
    get_notifications_for_service
)

from notifications_utils.template import get_sms_fragment_count

from tests.app.conftest import sample_job
from tests.app.conftest import sample_notification


def test_should_by_able_to_update_reference_by_id(sample_notification):
    assert not Notification.query.get(sample_notification.id).reference
    count = update_notification_reference_by_id(sample_notification.id, 'reference')
    assert count == 1
    assert Notification.query.get(sample_notification.id).reference == 'reference'


def test_should_by_able_to_update_status_by_reference(sample_email_template, ses_provider):
    data = _notification_json(sample_email_template)

    notification = Notification(**data)
    dao_create_notification(
        notification,
        sample_email_template.template_type,
        ses_provider.identifier)

    assert Notification.query.get(notification.id).status == "sending"
    update_notification_reference_by_id(notification.id, 'reference')
    update_notification_status_by_reference('reference', 'delivered', 'delivered')
    assert Notification.query.get(notification.id).status == 'delivered'
    assert NotificationStatistics.query.filter_by(
        service_id=sample_email_template.service.id
    ).one().emails_delivered == 1
    assert NotificationStatistics.query.filter_by(
        service_id=sample_email_template.service.id
    ).one().emails_requested == 1
    assert NotificationStatistics.query.filter_by(
        service_id=sample_email_template.service.id
    ).one().emails_failed == 0


def test_should_by_able_to_update_status_by_id(sample_notification):
    assert Notification.query.get(sample_notification.id).status == 'sending'
    count = update_notification_status_by_id(sample_notification.id, 'delivered', 'delivered')
    assert count == 1
    assert Notification.query.get(sample_notification.id).status == 'delivered'
    assert NotificationStatistics.query.filter_by(
        service_id=sample_notification.service.id
    ).one().sms_delivered == 1
    assert NotificationStatistics.query.filter_by(
        service_id=sample_notification.service.id
    ).one().sms_requested == 1
    assert NotificationStatistics.query.filter_by(
        service_id=sample_notification.service.id
    ).one().sms_failed == 0


def test_should_be_able_to_record_statistics_failure_for_sms(sample_notification):
    assert Notification.query.get(sample_notification.id).status == 'sending'
    count = update_notification_status_by_id(sample_notification.id, 'delivered', 'failure')
    assert count == 1
    assert Notification.query.get(sample_notification.id).status == 'delivered'
    assert NotificationStatistics.query.filter_by(
        service_id=sample_notification.service.id
    ).one().sms_delivered == 0
    assert NotificationStatistics.query.filter_by(
        service_id=sample_notification.service.id
    ).one().sms_requested == 1
    assert NotificationStatistics.query.filter_by(
        service_id=sample_notification.service.id
    ).one().sms_failed == 1


def test_should_be_able_to_record_statistics_failure_for_email(sample_email_template, ses_provider):
    data = _notification_json(sample_email_template)

    notification = Notification(**data)
    dao_create_notification(notification, sample_email_template.template_type, ses_provider.identifier)

    update_notification_reference_by_id(notification.id, 'reference')
    count = update_notification_status_by_reference('reference', 'failed', 'failure')
    assert count == 1
    assert Notification.query.get(notification.id).status == 'failed'
    assert NotificationStatistics.query.filter_by(
        service_id=notification.service.id
    ).one().emails_delivered == 0
    assert NotificationStatistics.query.filter_by(
        service_id=notification.service.id
    ).one().emails_requested == 1
    assert NotificationStatistics.query.filter_by(
        service_id=notification.service.id
    ).one().emails_failed == 1


def test_should_return_zero_count_if_no_notification_with_id():
    assert update_notification_status_by_id(str(uuid.uuid4()), 'delivered', 'delivered') == 0


def test_should_return_zero_count_if_no_notification_with_reference():
    assert update_notification_status_by_reference('something', 'delivered', 'delivered') == 0


def test_should_be_able_to_get_statistics_for_a_service(sample_template, mmg_provider):
    data = _notification_json(sample_template)

    notification = Notification(**data)
    dao_create_notification(notification, sample_template.template_type, mmg_provider.identifier)

    stats = dao_get_notification_statistics_for_service(sample_template.service.id)
    assert len(stats) == 1
    assert stats[0].emails_requested == 0
    assert stats[0].sms_requested == 1
    assert stats[0].sms_delivered == 0
    assert stats[0].sms_failed == 0
    assert stats[0].day == notification.created_at.date()
    assert stats[0].service_id == notification.service_id
    assert stats[0].emails_requested == 0
    assert stats[0].emails_delivered == 0
    assert stats[0].emails_failed == 0


def test_should_be_able_to_get_statistics_for_a_service_for_a_day(sample_template, mmg_provider):
    now = datetime.utcnow()
    data = _notification_json(sample_template)
    notification = Notification(**data)
    dao_create_notification(notification, sample_template.template_type, mmg_provider.identifier)
    stat = dao_get_notification_statistics_for_service_and_day(
        sample_template.service.id, now.date()
    )
    assert stat.emails_requested == 0
    assert stat.emails_failed == 0
    assert stat.emails_delivered == 0
    assert stat.sms_requested == 1
    assert stat.sms_failed == 0
    assert stat.sms_delivered == 0
    assert stat.day == notification.created_at.date()
    assert stat.service_id == notification.service_id


def test_should_return_none_if_no_statistics_for_a_service_for_a_day(sample_template, mmg_provider):
    data = _notification_json(sample_template)

    notification = Notification(**data)
    dao_create_notification(notification, sample_template.template_type, mmg_provider.identifier)
    assert not dao_get_notification_statistics_for_service_and_day(
        sample_template.service.id, (datetime.utcnow() - timedelta(days=1)).date()
    )


def test_should_be_able_to_get_all_statistics_for_a_service(sample_template, mmg_provider):
    data = _notification_json(sample_template)

    notification_1 = Notification(**data)
    notification_2 = Notification(**data)
    notification_3 = Notification(**data)
    dao_create_notification(notification_1, sample_template.template_type, mmg_provider.identifier)
    dao_create_notification(notification_2, sample_template.template_type, mmg_provider.identifier)
    dao_create_notification(notification_3, sample_template.template_type, mmg_provider.identifier)

    stats = dao_get_notification_statistics_for_service(sample_template.service.id)
    assert len(stats) == 1
    assert stats[0].emails_requested == 0
    assert stats[0].sms_requested == 3


def test_should_be_able_to_get_all_statistics_for_a_service_for_several_days(sample_template, mmg_provider):
    data = _notification_json(sample_template)

    today = datetime.utcnow()
    yesterday = datetime.utcnow() - timedelta(days=1)
    two_days_ago = datetime.utcnow() - timedelta(days=2)
    data.update({
        'created_at': today
    })
    notification_1 = Notification(**data)
    data.update({
        'created_at': yesterday
    })
    notification_2 = Notification(**data)
    data.update({
        'created_at': two_days_ago
    })
    notification_3 = Notification(**data)
    dao_create_notification(notification_1, sample_template.template_type, mmg_provider.identifier)
    dao_create_notification(notification_2, sample_template.template_type, mmg_provider.identifier)
    dao_create_notification(notification_3, sample_template.template_type, mmg_provider.identifier)

    stats = dao_get_notification_statistics_for_service(sample_template.service.id)
    assert len(stats) == 3
    assert stats[0].emails_requested == 0
    assert stats[0].sms_requested == 1
    assert stats[0].day == today.date()
    assert stats[1].emails_requested == 0
    assert stats[1].sms_requested == 1
    assert stats[1].day == yesterday.date()
    assert stats[2].emails_requested == 0
    assert stats[2].sms_requested == 1
    assert stats[2].day == two_days_ago.date()


def test_should_be_empty_list_if_no_statistics_for_a_service(sample_service):
    assert len(dao_get_notification_statistics_for_service(sample_service.id)) == 0


def test_should_be_able_to_get_all_statistics_for_a_service_for_several_days_previous(sample_template,
                                                                                      mmg_provider):
    data = _notification_json(sample_template)

    today = datetime.utcnow()
    seven_days_ago = datetime.utcnow() - timedelta(days=7)
    eight_days_ago = datetime.utcnow() - timedelta(days=8)
    data.update({
        'created_at': today
    })
    notification_1 = Notification(**data)
    data.update({
        'created_at': seven_days_ago
    })
    notification_2 = Notification(**data)
    data.update({
        'created_at': eight_days_ago
    })
    notification_3 = Notification(**data)
    dao_create_notification(notification_1, sample_template.template_type, mmg_provider.identifier)
    dao_create_notification(notification_2, sample_template.template_type, mmg_provider.identifier)
    dao_create_notification(notification_3, sample_template.template_type, mmg_provider.identifier)

    stats = dao_get_notification_statistics_for_service(
        sample_template.service.id, 7
    )
    assert len(stats) == 2
    assert stats[0].emails_requested == 0
    assert stats[0].sms_requested == 1
    assert stats[0].day == today.date()
    assert stats[1].emails_requested == 0
    assert stats[1].sms_requested == 1
    assert stats[1].day == seven_days_ago.date()


def test_save_notification_creates_sms_and_template_stats(sample_template, sample_job, mmg_provider):
    assert Notification.query.count() == 0
    assert NotificationStatistics.query.count() == 0
    assert TemplateStatistics.query.count() == 0

    data = _notification_json(sample_template, sample_job.id)

    notification = Notification(**data)
    dao_create_notification(notification, sample_template.template_type, mmg_provider.identifier)

    assert Notification.query.count() == 1
    notification_from_db = Notification.query.all()[0]
    assert notification_from_db.id
    assert data['to'] == notification_from_db.to
    assert data['job_id'] == notification_from_db.job_id
    assert data['service'] == notification_from_db.service
    assert data['template'] == notification_from_db.template
    assert data['created_at'] == notification_from_db.created_at
    assert 'sending' == notification_from_db.status
    assert Job.query.get(sample_job.id).notifications_sent == 1

    stats = NotificationStatistics.query.filter(
        NotificationStatistics.service_id == sample_template.service.id
    ).first()

    assert stats.emails_requested == 0
    assert stats.sms_requested == 1

    template_stats = TemplateStatistics.query.filter(TemplateStatistics.service_id == sample_template.service.id,
                                                     TemplateStatistics.template_id == sample_template.id).first()

    assert template_stats.service_id == sample_template.service.id
    assert template_stats.template_id == sample_template.id
    assert template_stats.usage_count == 1


def test_save_notification_and_create_email_and_template_stats(sample_email_template, sample_job, ses_provider):

    assert Notification.query.count() == 0
    assert NotificationStatistics.query.count() == 0
    assert TemplateStatistics.query.count() == 0

    data = _notification_json(sample_email_template, sample_job.id)

    notification = Notification(**data)
    dao_create_notification(notification, sample_email_template.template_type, ses_provider.identifier)

    assert Notification.query.count() == 1
    notification_from_db = Notification.query.all()[0]
    assert notification_from_db.id
    assert data['to'] == notification_from_db.to
    assert data['job_id'] == notification_from_db.job_id
    assert data['service'] == notification_from_db.service
    assert data['template'] == notification_from_db.template
    assert data['created_at'] == notification_from_db.created_at
    assert 'sending' == notification_from_db.status
    assert Job.query.get(sample_job.id).notifications_sent == 1

    stats = NotificationStatistics.query.filter(
        NotificationStatistics.service_id == sample_email_template.service.id
    ).first()

    assert stats.emails_requested == 1
    assert stats.sms_requested == 0

    template_stats = TemplateStatistics.query.filter(TemplateStatistics.service_id == sample_email_template.service.id,
                                                     TemplateStatistics.template_id == sample_email_template.id).first()  # noqa

    assert template_stats.service_id == sample_email_template.service.id
    assert template_stats.template_id == sample_email_template.id
    assert template_stats.usage_count == 1


@freeze_time("2016-01-01 00:00:00.000000")
def test_save_notification_handles_midnight_properly(sample_template, sample_job, mmg_provider):
    assert Notification.query.count() == 0
    data = _notification_json(sample_template, sample_job.id)

    notification = Notification(**data)
    dao_create_notification(notification, sample_template.template_type, mmg_provider.identifier)

    assert Notification.query.count() == 1

    stats = NotificationStatistics.query.filter(
        NotificationStatistics.service_id == sample_template.service.id
    ).first()

    assert stats.day == date(2016, 1, 1)


@freeze_time("2016-01-01 23:59:59.999999")
def test_save_notification_handles_just_before_midnight_properly(sample_template, sample_job, mmg_provider):
    assert Notification.query.count() == 0
    data = _notification_json(sample_template, sample_job.id)

    notification = Notification(**data)
    dao_create_notification(notification, sample_template.template_type, mmg_provider.identifier)

    assert Notification.query.count() == 1

    stats = NotificationStatistics.query.filter(
        NotificationStatistics.service_id == sample_template.service.id
    ).first()

    assert stats.day == date(2016, 1, 1)


def test_save_notification_and_increment_email_stats(sample_email_template, sample_job, ses_provider):
    assert Notification.query.count() == 0
    data = _notification_json(sample_email_template, sample_job.id)

    notification_1 = Notification(**data)
    notification_2 = Notification(**data)
    dao_create_notification(notification_1, sample_email_template.template_type, ses_provider.identifier)

    assert Notification.query.count() == 1

    stats1 = NotificationStatistics.query.filter(
        NotificationStatistics.service_id == sample_email_template.service.id
    ).first()

    assert stats1.emails_requested == 1
    assert stats1.sms_requested == 0

    dao_create_notification(notification_2, sample_email_template.template_type, ses_provider.identifier)

    assert Notification.query.count() == 2

    stats2 = NotificationStatistics.query.filter(
        NotificationStatistics.service_id == sample_email_template.service.id
    ).first()

    assert stats2.emails_requested == 2
    assert stats2.sms_requested == 0


def test_save_notification_and_increment_sms_stats(sample_template, sample_job, mmg_provider):
    assert Notification.query.count() == 0
    data = _notification_json(sample_template, sample_job.id)

    notification_1 = Notification(**data)
    notification_2 = Notification(**data)
    dao_create_notification(notification_1, sample_template.template_type, mmg_provider.identifier)

    assert Notification.query.count() == 1

    stats1 = NotificationStatistics.query.filter(
        NotificationStatistics.service_id == sample_template.service.id
    ).first()

    assert stats1.emails_requested == 0
    assert stats1.sms_requested == 1

    dao_create_notification(notification_2, sample_template.template_type, mmg_provider.identifier)

    assert Notification.query.count() == 2

    stats2 = NotificationStatistics.query.filter(
        NotificationStatistics.service_id == sample_template.service.id
    ).first()

    assert stats2.emails_requested == 0
    assert stats2.sms_requested == 2


def test_not_save_notification_and_not_create_stats_on_commit_error(sample_template, sample_job, mmg_provider):
    random_id = str(uuid.uuid4())

    assert Notification.query.count() == 0
    data = _notification_json(sample_template, random_id)

    notification = Notification(**data)
    with pytest.raises(SQLAlchemyError):
        dao_create_notification(notification, sample_template.template_type, mmg_provider.identifier)

    assert Notification.query.count() == 0
    assert Job.query.get(sample_job.id).notifications_sent == 0
    assert NotificationStatistics.query.count() == 0
    assert TemplateStatistics.query.count() == 0


def test_save_notification_and_increment_job(sample_template, sample_job, mmg_provider):
    assert Notification.query.count() == 0
    data = _notification_json(sample_template, sample_job.id)

    notification = Notification(**data)
    dao_create_notification(notification, sample_template.template_type, mmg_provider.identifier)

    assert Notification.query.count() == 1
    notification_from_db = Notification.query.all()[0]
    assert notification_from_db.id
    assert data['to'] == notification_from_db.to
    assert data['job_id'] == notification_from_db.job_id
    assert data['service'] == notification_from_db.service
    assert data['template'] == notification_from_db.template
    assert data['created_at'] == notification_from_db.created_at
    assert 'sending' == notification_from_db.status
    assert Job.query.get(sample_job.id).notifications_sent == 1

    notification_2 = Notification(**data)
    dao_create_notification(notification_2, sample_template.template_type, mmg_provider.identifier)
    assert Notification.query.count() == 2
    assert Job.query.get(sample_job.id).notifications_sent == 2


def test_should_not_increment_job_if_notification_fails_to_persist(sample_template, sample_job, mmg_provider):
    random_id = str(uuid.uuid4())
    assert Notification.query.count() == 0
    data = {
        'id': random_id,
        'to': '+44709123456',
        'job_id': sample_job.id,
        'service_id': sample_template.service.id,
        'service': sample_template.service,
        'template': sample_template,
        'template_id': sample_template.id,
        'template_version': sample_template.version,
        'created_at': datetime.utcnow(),
        'content_char_count': 160
    }

    notification_1 = Notification(**data)
    dao_create_notification(notification_1, sample_template.template_type, mmg_provider.identifier)

    assert Notification.query.count() == 1
    assert Job.query.get(sample_job.id).notifications_sent == 1
    job_last_updated_at = Job.query.get(sample_job.id).updated_at

    notification_2 = Notification(**data)
    with pytest.raises(SQLAlchemyError):
        dao_create_notification(notification_2, sample_template.template_type, mmg_provider.identifier)

    assert Notification.query.count() == 1
    assert Job.query.get(sample_job.id).notifications_sent == 1
    assert Job.query.get(sample_job.id).updated_at == job_last_updated_at


def test_save_notification_and_increment_correct_job(notify_db, notify_db_session, sample_template, mmg_provider):
    job_1 = sample_job(notify_db, notify_db_session, sample_template.service)
    job_2 = sample_job(notify_db, notify_db_session, sample_template.service)

    assert Notification.query.count() == 0
    data = _notification_json(sample_template, job_1.id)

    notification = Notification(**data)
    dao_create_notification(notification, sample_template.template_type, mmg_provider.identifier)

    assert Notification.query.count() == 1
    notification_from_db = Notification.query.all()[0]
    assert notification_from_db.id
    assert data['to'] == notification_from_db.to
    assert data['job_id'] == notification_from_db.job_id
    assert data['service'] == notification_from_db.service
    assert data['template'] == notification_from_db.template
    assert data['created_at'] == notification_from_db.created_at
    assert 'sending' == notification_from_db.status
    assert Job.query.get(job_1.id).notifications_sent == 1
    assert Job.query.get(job_2.id).notifications_sent == 0


def test_save_notification_with_no_job(sample_template, mmg_provider):
    assert Notification.query.count() == 0
    data = _notification_json(sample_template)

    notification = Notification(**data)
    dao_create_notification(notification, sample_template.template_type, mmg_provider.identifier)

    assert Notification.query.count() == 1
    notification_from_db = Notification.query.all()[0]
    assert notification_from_db.id
    assert data['to'] == notification_from_db.to
    assert data['service'] == notification_from_db.service
    assert data['template'] == notification_from_db.template
    assert data['created_at'] == notification_from_db.created_at
    assert 'sending' == notification_from_db.status


def test_get_notification(sample_notification):
    notifcation_from_db = get_notification(
        sample_notification.service.id,
        sample_notification.id)
    assert sample_notification == notifcation_from_db


def test_save_notification_no_job_id(sample_template, mmg_provider):
    assert Notification.query.count() == 0
    to = '+44709123456'
    data = _notification_json(sample_template)

    notification = Notification(**data)
    dao_create_notification(notification, sample_template.template_type, mmg_provider.identifier)

    assert Notification.query.count() == 1
    notification_from_db = Notification.query.all()[0]
    assert notification_from_db.id
    assert data['to'] == notification_from_db.to
    assert data['service'] == notification_from_db.service
    assert data['template'] == notification_from_db.template
    assert 'sending' == notification_from_db.status


def test_get_notification_for_job(sample_notification):
    notifcation_from_db = get_notification_for_job(
        sample_notification.service.id,
        sample_notification.job_id,
        sample_notification.id)
    assert sample_notification == notifcation_from_db


def test_get_all_notifications_for_job(notify_db, notify_db_session, sample_job):
    from tests.app.conftest import sample_notification
    for i in range(0, 5):
        try:
            sample_notification(notify_db,
                                notify_db_session,
                                service=sample_job.service,
                                template=sample_job.template,
                                job=sample_job)
        except IntegrityError:
            pass

    notifcations_from_db = get_notifications_for_job(sample_job.service.id, sample_job.id).items
    assert len(notifcations_from_db) == 5
    stats = NotificationStatistics.query.filter(
        NotificationStatistics.service_id == sample_job.service.id
    ).first()

    assert stats.emails_requested == 0
    assert stats.sms_requested == 5


def test_update_notification(sample_notification, sample_template):
    assert sample_notification.status == 'sending'
    sample_notification.status = 'failed'
    dao_update_notification(sample_notification)
    notification_from_db = Notification.query.get(sample_notification.id)
    assert notification_from_db.status == 'failed'


@freeze_time("2016-01-10 12:00:00.000000")
def test_should_delete_notifications_after_seven_days(notify_db, notify_db_session):

    assert len(Notification.query.all()) == 0

    # create one notification a day between 1st and 9th from 11:00 to 19:00
    for i in range(1, 11):
        past_date = '2016-01-{0:02d}  {0:02d}:00:00.000000'.format(i, i)
        with freeze_time(past_date):
            sample_notification(notify_db, notify_db_session, created_at=datetime.utcnow(), status="failed")

    all_notifications = Notification.query.all()
    assert len(all_notifications) == 10

    # Records from before 3rd should be deleted
    delete_notifications_created_more_than_a_week_ago('failed')
    remaining_notifications = Notification.query.all()
    assert len(remaining_notifications) == 8
    assert remaining_notifications[0].created_at.date() == date(2016, 1, 3)


def test_should_not_delete_failed_notifications_before_seven_days(notify_db, notify_db_session):
    should_delete = datetime.utcnow() - timedelta(days=8)
    do_not_delete = datetime.utcnow() - timedelta(days=7)
    sample_notification(notify_db, notify_db_session, created_at=should_delete, status="failed",
                        to_field="should_delete")
    sample_notification(notify_db, notify_db_session, created_at=do_not_delete, status="failed",
                        to_field="do_not_delete")
    assert len(Notification.query.all()) == 2
    delete_notifications_created_more_than_a_week_ago('failed')
    assert len(Notification.query.all()) == 1
    assert Notification.query.first().to == 'do_not_delete'


@freeze_time("2016-03-30")
def test_save_new_notification_creates_template_stats(sample_template, sample_job, mmg_provider):
    assert Notification.query.count() == 0
    assert TemplateStatistics.query.count() == 0
    data = _notification_json(sample_template, sample_job.id)

    notification = Notification(**data)
    dao_create_notification(notification, sample_template.template_type, mmg_provider.identifier)

    assert TemplateStatistics.query.count() == 1
    template_stats = TemplateStatistics.query.filter(TemplateStatistics.service_id == sample_template.service.id,
                                                     TemplateStatistics.template_id == sample_template.id).first()
    assert template_stats.service_id == sample_template.service.id
    assert template_stats.template_id == sample_template.id
    assert template_stats.usage_count == 1
    assert template_stats.day == date(2016, 3, 30)


@freeze_time("2016-03-30")
def test_save_new_notification_creates_template_stats_per_day(sample_template, sample_job, mmg_provider):
    assert Notification.query.count() == 0
    assert TemplateStatistics.query.count() == 0
    data = _notification_json(sample_template, sample_job.id)

    notification = Notification(**data)
    dao_create_notification(notification, sample_template.template_type, mmg_provider.identifier)

    assert TemplateStatistics.query.count() == 1
    template_stats = TemplateStatistics.query.filter(TemplateStatistics.service_id == sample_template.service.id,
                                                     TemplateStatistics.template_id == sample_template.id).first()
    assert template_stats.service_id == sample_template.service.id
    assert template_stats.template_id == sample_template.id
    assert template_stats.usage_count == 1
    assert template_stats.day == date(2016, 3, 30)

    # move on one day
    with freeze_time('2016-03-31'):
        assert TemplateStatistics.query.count() == 1
        new_notification = Notification(**data)
        dao_create_notification(new_notification, sample_template.template_type, mmg_provider.identifier)

    assert TemplateStatistics.query.count() == 2
    first_stats = TemplateStatistics.query.filter(TemplateStatistics.day == datetime(2016, 3, 30)).first()
    second_stats = TemplateStatistics.query.filter(TemplateStatistics.day == datetime(2016, 3, 31)).first()

    assert first_stats.template_id == second_stats.template_id
    assert first_stats.service_id == second_stats.service_id

    assert first_stats.day == date(2016, 3, 30)
    assert first_stats.usage_count == 1

    assert second_stats.day == date(2016, 3, 31)
    assert second_stats.usage_count == 1


def test_save_another_notification_increments_template_stats(sample_template, sample_job, mmg_provider):
    assert Notification.query.count() == 0
    assert TemplateStatistics.query.count() == 0
    data = _notification_json(sample_template, sample_job.id)

    notification_1 = Notification(**data)
    notification_2 = Notification(**data)
    dao_create_notification(notification_1, sample_template.template_type, mmg_provider.identifier)

    assert TemplateStatistics.query.count() == 1
    template_stats = TemplateStatistics.query.filter(TemplateStatistics.service_id == sample_template.service.id,
                                                     TemplateStatistics.template_id == sample_template.id).first()
    assert template_stats.service_id == sample_template.service.id
    assert template_stats.template_id == sample_template.id
    assert template_stats.usage_count == 1

    dao_create_notification(notification_2, sample_template.template_type, mmg_provider.identifier)

    assert TemplateStatistics.query.count() == 1
    template_stats = TemplateStatistics.query.filter(TemplateStatistics.service_id == sample_template.service.id,
                                                     TemplateStatistics.template_id == sample_template.id).first()
    assert template_stats.usage_count == 2


def test_successful_notification_inserts_followed_by_failure_does_not_increment_template_stats(sample_template,
                                                                                               sample_job,
                                                                                               mmg_provider):
    assert Notification.query.count() == 0
    assert NotificationStatistics.query.count() == 0
    assert TemplateStatistics.query.count() == 0

    data = _notification_json(sample_template, sample_job.id)

    notification_1 = Notification(**data)
    notification_2 = Notification(**data)
    notification_3 = Notification(**data)
    dao_create_notification(notification_1, sample_template.template_type, mmg_provider.identifier)
    dao_create_notification(notification_2, sample_template.template_type, mmg_provider.identifier)
    dao_create_notification(notification_3, sample_template.template_type, mmg_provider.identifier)

    assert NotificationStatistics.query.count() == 1
    notication_stats = NotificationStatistics.query.filter(
        NotificationStatistics.service_id == sample_template.service.id
    ).first()
    assert notication_stats.sms_requested == 3

    assert TemplateStatistics.query.count() == 1
    template_stats = TemplateStatistics.query.filter(TemplateStatistics.service_id == sample_template.service.id,
                                                     TemplateStatistics.template_id == sample_template.id).first()
    assert template_stats.service_id == sample_template.service.id
    assert template_stats.template_id == sample_template.id
    assert template_stats.usage_count == 3

    failing_notification = Notification(**data)
    try:
        # Mess up db in really bad way
        db.session.execute('DROP TABLE TEMPLATE_STATISTICS')
        dao_create_notification(failing_notification, sample_template.template_type, mmg_provider.identifier)
    except Exception as e:
        # There should be no additional notification stats or counts
        assert NotificationStatistics.query.count() == 1
        notication_stats = NotificationStatistics.query.filter(
            NotificationStatistics.service_id == sample_template.service.id
        ).first()
        assert notication_stats.sms_requested == 3


@freeze_time("2016-03-30")
def test_get_template_stats_for_service_returns_stats_in_reverse_date_order(sample_template,
                                                                            sample_job,
                                                                            mmg_provider):

    template_stats = dao_get_template_statistics_for_service(sample_template.service.id)
    assert len(template_stats) == 0
    data = _notification_json(sample_template, sample_job.id)

    notification = Notification(**data)
    dao_create_notification(notification, sample_template.template_type, mmg_provider.identifier)

    # move on one day
    with freeze_time('2016-03-31'):
        new_notification = Notification(**data)
        dao_create_notification(new_notification, sample_template.template_type, mmg_provider.identifier)

    # move on one more day
    with freeze_time('2016-04-01'):
        new_notification = Notification(**data)
        dao_create_notification(new_notification, sample_template.template_type, mmg_provider.identifier)

    template_stats = dao_get_template_statistics_for_service(sample_template.service_id)
    assert len(template_stats) == 3
    assert template_stats[0].day == date(2016, 4, 1)
    assert template_stats[1].day == date(2016, 3, 31)
    assert template_stats[2].day == date(2016, 3, 30)


@freeze_time('2016-04-09')
def test_get_template_stats_for_service_returns_stats_can_limit_number_of_days_returned(sample_template):

    template_stats = dao_get_template_statistics_for_service(sample_template.service.id)
    assert len(template_stats) == 0

    # Make 9 stats records from 1st to 9th April
    for i in range(1, 10):
        past_date = '2016-04-0{}'.format(i)
        with freeze_time(past_date):
            template_stats = TemplateStatistics(template_id=sample_template.id,
                                                service_id=sample_template.service_id)
            db.session.add(template_stats)
            db.session.commit()

    # Retrieve last week of stats
    template_stats = dao_get_template_statistics_for_service(sample_template.service_id, limit_days=7)
    assert len(template_stats) == 8
    assert template_stats[0].day == date(2016, 4, 9)
    # Final day of stats should be the same as today, eg Monday
    assert template_stats[0].day.isoweekday() == template_stats[7].day.isoweekday()
    assert template_stats[7].day == date(2016, 4, 2)


@freeze_time('2016-04-09')
def test_get_template_stats_for_service_returns_stats_returns_all_stats_if_no_limit(sample_template):

    template_stats = dao_get_template_statistics_for_service(sample_template.service.id)
    assert len(template_stats) == 0

    # make 9 stats records from 1st to 9th April
    for i in range(1, 10):
        past_date = '2016-04-0{}'.format(i)
        with freeze_time(past_date):
            template_stats = TemplateStatistics(template_id=sample_template.id,
                                                service_id=sample_template.service_id)
            db.session.add(template_stats)
            db.session.commit()

    template_stats = dao_get_template_statistics_for_service(sample_template.service_id)
    assert len(template_stats) == 9
    assert template_stats[0].day == date(2016, 4, 9)
    assert template_stats[8].day == date(2016, 4, 1)


@freeze_time('2016-04-30')
def test_get_template_stats_for_service_returns_no_result_if_no_usage_within_limit_days(sample_template):

    template_stats = dao_get_template_statistics_for_service(sample_template.service.id)
    assert len(template_stats) == 0

    # make 9 stats records from 1st to 9th April - no data after 10th
    for i in range(1, 10):
        past_date = '2016-04-0{}'.format(i)
        with freeze_time(past_date):
            template_stats = TemplateStatistics(template_id=sample_template.id,
                                                service_id=sample_template.service_id)
            db.session.add(template_stats)
            db.session.commit()

    # Retrieve a week of stats - read date is 2016-04-30
    template_stats = dao_get_template_statistics_for_service(sample_template.service_id, limit_days=7)
    assert len(template_stats) == 0

    # Retrieve a month of stats - read date is 2016-04-30
    template_stats = dao_get_template_statistics_for_service(sample_template.service_id, limit_days=30)
    assert len(template_stats) == 9


def test_get_template_stats_for_service_with_limit_if_no_records_returns_empty_list(sample_template):
    template_stats = dao_get_template_statistics_for_service(sample_template.service.id, limit_days=7)
    assert len(template_stats) == 0


@freeze_time("2016-01-10")
def test_should_limit_notifications_return_by_day_limit_plus_one(notify_db, notify_db_session, sample_service):

    assert len(Notification.query.all()) == 0

    # create one notification a day between 1st and 9th
    for i in range(1, 11):
        past_date = '2016-01-{0:02d}'.format(i)
        with freeze_time(past_date):
            sample_notification(notify_db, notify_db_session, created_at=datetime.utcnow(), status="failed")

    all_notifications = Notification.query.all()
    assert len(all_notifications) == 10

    all_notifications = get_notifications_for_service(sample_service.id, limit_days=10).items
    assert len(all_notifications) == 10

    all_notifications = get_notifications_for_service(sample_service.id, limit_days=1).items
    assert len(all_notifications) == 2


@pytest.mark.parametrize(
    "char_count, expected_sms_fragment_count",
    [
        (159, 1),
        (160, 1),
        (161, 2),
        (306, 2),
        (307, 3),
        (459, 3),
        (460, 4),
        (461, 4)
    ])
def test_sms_fragment_count(char_count, expected_sms_fragment_count):
    assert get_sms_fragment_count(char_count) == expected_sms_fragment_count


def _notification_json(sample_template, job_id=None):
    data = {
        'to': '+44709123456',
        'service': sample_template.service,
        'service_id': sample_template.service.id,
        'template': sample_template,
        'template_id': sample_template.id,
        'template_version': sample_template.version,
        'created_at': datetime.utcnow(),
        'content_char_count': 160
    }
    if job_id:
        data.update({'job_id': job_id})
    return data
