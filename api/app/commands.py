import sys
import csv
import functools
import uuid
from datetime import datetime, timedelta
from decimal import Decimal

import click
import flask
from click_datetime import Datetime as click_dt
from flask import current_app
from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy.exc import IntegrityError
from notifications_utils.statsd_decorators import statsd

from app import db
from app.celery.tasks import check_celery_health
from app.celery.scheduled_tasks import send_total_sent_notifications_to_performance_platform
from app.celery.letters_pdf_tasks import create_letters_pdf
from app.clients.sms.telstra import get_telstra_responses
from app.config import QueueNames
from app.dao.jobs_dao import (
    dao_get_jobs,
    dao_get_job_by_id,
)
from app.dao.monthly_billing_dao import (
    create_or_update_monthly_billing,
    get_monthly_billing_by_notification_type,
    get_service_ids_that_need_billing_populated,
    get_all_monthly_billing,
)
from app.dao.notifications_dao import (
    get_notification_by_id,
    dao_get_notification_history_by_id,
)
from app.dao.provider_rates_dao import (
    create_provider_rates as dao_create_provider_rates,
    list_provider_rates as dao_list_provider_rates,
)
from app.dao.rates_dao import (
    list_rates as dao_list_rates,
)
from app.dao.services_dao import (
    delete_service_and_all_associated_db_objects,
    dao_fetch_all_services_by_user,
    dao_fetch_all_services,
    dao_set_service_preferred_sms_provider,
)
import app.dao.service_sms_sender_dao as sms_sender_dao
from app.dao.users_dao import (
    delete_model_user,
    delete_user_verify_codes,
    get_users_by_platform_admin,
    grant_platform_admin_by_email,
    revoke_platform_admin_by_email,
    set_email_updated_date_earlier_by_email,
    set_password_updated_date_earlier_by_email,
)
from app.models import PROVIDERS, SMS_PROVIDERS, User, SMS_TYPE, EMAIL_TYPE, Notification
from app.notifications.callbacks import check_for_callback_and_send_delivery_status_to_service
from app.performance_platform.processing_time import (send_processing_time_for_start_and_end)
from app.utils import (
    get_sydney_midnight_in_utc,
    get_midnight_for_day_before,
    convert_aet_to_utc,
)
from app import telstra_sms_client, twilio_sms_client
from app.sap.oauth2 import OAuth2Client as SAPOAuth2Client


@click.group(name='command', help='Additional commands')
def command_group():
    pass


class notify_command:
    def __init__(self, name=None):
        self.name = name

    def __call__(self, func):
        # we need to call the flask with_appcontext decorator to ensure the config is loaded, db connected etc etc.
        # we also need to use functools.wraps to carry through the names and docstrings etc of the functions.
        # Then we need to turn it into a click.Command - that's what command_group.add_command expects.
        @click.command(name=self.name)
        @functools.wraps(func)
        @flask.cli.with_appcontext
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        command_group.add_command(wrapper)

        return wrapper


@notify_command()
@click.option('-n', '--notification_id', required=True, type=click.UUID)
def debug_notification(notification_id):
    """
    Print debug information about a particular notification.
    """
    notification = get_notification_by_id(notification_id)
    if not notification:
        current_app.logger.error(f"Could not find the notification with ID {notification_id}")
        sys.exit(1)
    from pprint import pprint
    pprint("Notification:")
    pprint(vars(notification))
    history = dao_get_notification_history_by_id(notification_id)
    if not history:
        current_app.logger.error(f"Could not find the notification history with ID {notification_id}")
        sys.exit(1)
    pprint("History:")
    pprint(vars(history))


@notify_command()
@click.option('-p', '--provider_name', required=True, type=click.Choice(PROVIDERS))
@click.option('-c', '--cost', required=True, help='Cost (pence) per message including decimals', type=float)
@click.option('-d', '--valid_from', required=True, type=click_dt(format='%Y-%m-%dT%H:%M:%S'))
def create_provider_rates(provider_name, cost, valid_from):
    """
    Backfill rates for a given provider
    """
    cost = Decimal(cost)
    dao_create_provider_rates(provider_name, valid_from, cost)


@notify_command()
def list_provider_rates():
    writer = csv.writer(sys.stdout)
    writer.writerow([
        'id',
        'valid_from',
        'rate',
        'provider_id',
        'provider_identifier',
    ])

    for r in dao_list_provider_rates():
        writer.writerow([
            r.id,
            r.valid_from,
            r.rate,
            r.provider.id,
            r.provider.identifier,
        ])


@notify_command()
def list_rates():
    writer = csv.writer(sys.stdout)
    writer.writerow([
        'id',
        'valid_from',
        'rate',
        'notification_type',
    ])

    for r in dao_list_rates():
        writer.writerow([
            r.id,
            r.valid_from,
            r.rate,
            r.notification_type,
        ])


@notify_command()
def list_monthly_billing():
    writer = csv.writer(sys.stdout)
    writer.writerow([
        'id',
        'service_id',
        'notification_type',
        'monthly_totals',
        'updated_at',
        'start_date',
        'end_date',
    ])

    for r in get_all_monthly_billing():
        writer.writerow([
            r.id,
            r.service_id,
            r.notification_type,
            r.monthly_totals,
            r.updated_at,
            r.start_date,
            r.end_date,
        ])


@notify_command()
@click.option('-u', '--user_email_prefix', required=True, help="""
    Functional test user email prefix. eg "notify-test-preview"
""")  # noqa
def purge_functional_test_data(user_email_prefix):
    """
    Remove non-seeded functional test data

    users, services, etc. Give an email prefix. Probably "notify-test-preview".
    """
    users = User.query.filter(User.email_address.like("{}%".format(user_email_prefix))).all()
    for usr in users:
        # Make sure the full email includes a uuid in it
        # Just in case someone decides to use a similar email address.
        try:
            uuid.UUID(usr.email_address.split("@")[0].split('+')[1])
        except ValueError:
            print("Skipping {} as the user email doesn't contain a UUID.".format(usr.email_address))
        else:
            services = dao_fetch_all_services_by_user(usr.id)
            if services:
                for service in services:
                    delete_service_and_all_associated_db_objects(service)
            else:
                delete_user_verify_codes(usr)
                delete_model_user(usr)


@notify_command()
@click.option('-y', '--year', required=True, help="e.g. 2017 (note: 2016/2017 is referred to as '2017'—ask an accountant and they'll refer to that FY as '2017')", type=int)
@click.option('-s', '--service_id', required=False, help="provide this to restrict the services to update to the given service", type=click.UUID)
def populate_monthly_billing(year, service_id):
    """
    Populate monthly billing table for all services for a given year.
    """
    def populate(service_id, year, month):
        aet_billing_month = datetime(year, month, 1)
        utc_billing_month = convert_aet_to_utc(aet_billing_month)
        create_or_update_monthly_billing(service_id, billing_month=utc_billing_month)

        sms_res = get_monthly_billing_by_notification_type(
            service_id, datetime(year, month, 1), SMS_TYPE
        )
        email_res = get_monthly_billing_by_notification_type(
            service_id, datetime(year, month, 1), EMAIL_TYPE
        )
        letter_res = get_monthly_billing_by_notification_type(
            service_id, datetime(year, month, 1), 'letter'
        )

        sms_totals = sms_res.monthly_totals if sms_res else 0
        email_totals = email_res.monthly_totals if email_res else 0
        letter_totals = letter_res.monthly_totals if letter_res else 0

        print(f"Finished populating data for {month} for service id {str(service_id)}")
        print(f"SMS: {sms_totals}")
        print(f"Email: {email_totals}")
        print(f"Letter: {letter_totals}")

    aet_start_date = datetime(year - 1, 7, 1)
    aet_end_date = datetime(year, 6, 30)

    utc_start_date = convert_aet_to_utc(aet_start_date)
    utc_end_date = convert_aet_to_utc(aet_end_date)

    service_ids = get_service_ids_that_need_billing_populated(
        start_date=utc_start_date, end_date=utc_end_date
    )
    start, end = 1, 13

    for sid in service_ids:
        if service_id is not None and service_id != sid.service_id:
            print(f"Skipped service {str(sid)} due to flag")
            continue

        print(f"Starting to populate data for service {str(sid)}")
        print(f"Starting populating monthly billing for {year}")
        for i in range(start, end):
            print(f"Population for {i}-{year}")
            populate(sid, year, i)


@notify_command()
@click.option('-s', '--start_date', required=True, help="start date inclusive", type=click_dt(format='%Y-%m-%d'))
@click.option('-e', '--end_date', required=True, help="end date inclusive", type=click_dt(format='%Y-%m-%d'))
def backfill_performance_platform_totals(start_date, end_date):
    """
    Send historical total messages sent to Performance Platform.

    WARNING: This does not overwrite existing data. You need to delete
             the existing data or Performance Platform will double-count.
    """

    delta = end_date - start_date

    print('Sending total messages sent for all days between {} and {}'.format(start_date, end_date))

    for i in range(delta.days + 1):

        process_date = start_date + timedelta(days=i)

        print('Sending total messages sent for {}'.format(
            process_date.isoformat()
        ))

        send_total_sent_notifications_to_performance_platform(process_date)


@notify_command()
@click.option('-s', '--start_date', required=True, help="start date inclusive", type=click_dt(format='%Y-%m-%d'))
@click.option('-e', '--end_date', required=True, help="end date inclusive", type=click_dt(format='%Y-%m-%d'))
def backfill_processing_time(start_date, end_date):
    """
    Send historical processing time to Performance Platform.
    """

    delta = end_date - start_date

    print('Sending notification processing-time data for all days between {} and {}'.format(start_date, end_date))

    for i in range(delta.days + 1):
        # because the tz conversion funcs talk about midnight, and the midnight before last,
        # we want to pretend we're running this from the next morning, so add one.
        process_date = start_date + timedelta(days=i + 1)

        process_start_date = get_midnight_for_day_before(process_date)
        process_end_date = get_sydney_midnight_in_utc(process_date)

        print('Sending notification processing-time for {} - {}'.format(
            process_start_date.isoformat(),
            process_end_date.isoformat()
        ))
        send_processing_time_for_start_and_end(process_start_date, process_end_date)


@notify_command('populate-annual-billing')
@click.option('-y', '--year', required=True, type=int,
              help="""The year to populate the annual billing data for, e.g. 2019""")
def populate_annual_billing(year):
    """
    add annual_billing for given year.
    """
    sql = """
    INSERT INTO annual_billing(id, service_id, free_sms_fragment_limit, financial_year_start,
            created_at, updated_at)
        SELECT uuid_in(md5(random()::text || now()::text)::cstring), id, 250000, :year, :now, :now
        FROM services
        WHERE id NOT IN(
            SELECT service_id
            FROM annual_billing
            WHERE financial_year_start = :year)
    """

    result = db.session.execute(sql, {"year": year, "now": datetime.utcnow()})
    db.session.commit()

    print("Populated annual billing {} for {} services".format(year, result.rowcount))


@notify_command(name='list-routes')
def list_routes():
    """List URLs of all application routes."""
    for rule in sorted(current_app.url_map.iter_rules(), key=lambda r: r.rule):
        print("{:10} {}".format(", ".join(rule.methods - set(['OPTIONS', 'HEAD'])), rule.rule))


@notify_command()
def list_platform_admins():
    print('>> Start listing platform admins')
    for user in sorted(get_users_by_platform_admin(), key=lambda u: u.email_address):
        print(user.email_address)
    print('<< End listing platform admins')


@notify_command()
@click.option('-e', '--email_address', required=True,
              help="""Full email address of the admin to revoke""")
def revoke_platform_admin(email_address):
    revoke_platform_admin_by_email(email_address)


@notify_command()
@click.option('-u', '--username', required=True,
              help="""Name of org member to promote as platform admin""")
def grant_platform_admin(username):
    grant_platform_admin_by_email(f"{username}@dta.gov.au")


@notify_command()
@click.option('-e', '--email_address', required=True,
              help="""Full email address of user""")
def set_email_updated_date_earlier(email_address):
    set_email_updated_date_earlier_by_email(email_address)


@notify_command()
@click.option('-e', '--email_address', required=True,
              help="""Full email address of user""")
def set_password_updated_date_earlier(email_address):
    set_password_updated_date_earlier_by_email(email_address)


@notify_command()
@click.option('-s', '--service_id', required=True, help="service to alter")
@click.option('-p', '--provider', help="sms provider to set as preferred")
def set_preferred_sms_provider(service_id, provider):
    dao_set_service_preferred_sms_provider(service_id, provider)


@notify_command(name='provision-telstra')
def provision_telstra_subscription():
    telstra_sms_client.provision_subscription()


@notify_command(name='get-telstra-message-status')
@click.option('-m', '--message_id',
              required=True,
              help="ID of the Telstra message to check")
def get_telstra_message_status(message_id):
    resp = telstra_sms_client.get_message_status(message_id=message_id)
    if len(resp) == 0:
        current_app.logger.error('Could not find the message with ID {}'.format(message_id))
        sys.exit(1)
    msg = resp[0]
    print('Sent to: {}'.format(msg.to))
    print('Sent at: {}'.format(msg.sent_timestamp))
    print('Received at: {}'.format(msg.received_timestamp))
    print('Telstra status: {}'.format(msg.delivery_status))
    if msg.delivery_status:
        print('Notify status: {}'.format(get_telstra_responses(msg.delivery_status)))


@notify_command(name='create-sap-oauth2-client')
@click.option('-i', '--client_id', required=True, help="The client's ID")
@click.option('-s', '--client_secret', required=True, help="The client's secret")
def create_sap_oauth2_client(client_id, client_secret):
    """
    You can generate a secure random string using the following Python code.

    > import string
    > import secrets
    > length = 48
    > ''.join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(length))
    """

    if len(client_id) != 48:
        current_app.logger.error('Client ID should be 48 characters long')
        sys.exit(1)

    if len(client_secret) < 48:
        current_app.logger.error('Client secret should be at least 48 characters long')
        sys.exit(1)

    client = SAPOAuth2Client(
        client_id=client_id,
        client_secret=client_secret
    )
    client.set_client_metadata({
        "grant_types": [
            "client_credentials"
        ]
    })

    try:
        db.session.add(client)
        db.session.commit()
    except IntegrityError as ex:
        if 'sap_oauth2_clients_client_id_key' in str(ex):
            current_app.logger.info('Client already exists with the provided client ID')
            sys.exit(0)
        raise ex


@notify_command(name='twilio-buy-available-phone-number')
@click.option('-c', '--country_code',
              required=True,
              help="The ISO country code of the country from which to purchase the phone number",
              )
@click.option('-a', '--address_sid',
              required=True,
              help="The Twilio address SID that must be supplied when purchasing the phone number",
              )
def twilio_buy_available_phone_number(country_code, address_sid):
    incoming_phone_number = twilio_sms_client.buy_available_phone_number(country_code, address_sid)

    if incoming_phone_number is None:
        current_app.logger.error('Could not find an available phone number to buy')
        sys.exit(1)

    print('Purchased phone number: {}'.format(incoming_phone_number.phone_number))
    print('SID: {}'.format(incoming_phone_number.sid))
    print('Capabilities: {}'.format(incoming_phone_number.capabilities))

    sql = """
        insert into inbound_numbers (id, number, provider, service_id, active, created_at, updated_at)
        values('{}', '{}', 'twilio', null, True, now(), null);
    """
    db.session.execute(sql.format(uuid.uuid4(), incoming_phone_number.phone_number))
    db.session.commit()

    print('Inbound phone number now available to allocate')


@notify_command(name='remove-sms-sender')
@click.option('-s', '--sms_sender_id',
              type=click.UUID, required=True,
              help="SMS sender ID of the non-default sender ID to be removed")
def remove_sms_sender(sms_sender_id):
    sms_sender_dao.dao_remove_sms_sender(sms_sender_id)


@notify_command(name='run-health-check')
@click.option('-m', '--message', required=True, help="the message to send")
def run_health_check(message):
    print('running health check')
    print(check_celery_health.apply_async((message,), queue=QueueNames.NOTIFY))


@notify_command(name='insert-inbound-number')
@click.option('-p', '--provider_name',
              required=True,
              type=click.Choice(SMS_PROVIDERS),
              help="The provider identifier to associate with the numbers (e.g. twilio, sap, telstra)",
              )
@click.option('-n', '--number',
              required=True,
              help="The mobile number in E.164 format to insert"
              )
@click.option('-i', '--ignore_existing',
              is_flag=True,
              help="Set this option to quietly ignore inbound numbers that have already been inserted"
              )
def insert_inbound_number(provider_name, number, ignore_existing):
    sql = """
    insert into inbound_numbers (id, number, provider, service_id, active, created_at, updated_at)
    values('{}', '{}', '{}', null, True, now(), null);
    """

    number = number.strip()

    try:
        db.session.execute(sql.format(uuid.uuid4(), number, provider_name))
        db.session.commit()

        print('Number inserted')
    except IntegrityError as ex:
        if 'inbound_numbers_number_key' not in str(ex):
            raise ex
        if not ignore_existing:
            raise ex

        db.session.rollback()
        print('Number already inserted')


@notify_command(name='contact-users')
def list_user_contacts():
    writer = csv.writer(sys.stdout)
    writer.writerow(['service_id', 'service_name', 'count_as_live', 'user_email_address'])

    for service in dao_fetch_all_services(only_active=True):
        for user in service.users:
            permissions = user.get_permissions(service_id=service.id)
            if 'manage_users' in permissions or 'manage_settings' in permissions:
                writer.writerow([service.id, service.name, service.count_as_live, user.email_address])


@notify_command(name='replay-create-pdf-letters')
@click.option('-n', '--notification_id', type=click.UUID, required=True,
              help="Notification id of the letter that needs the create_letters_pdf task replayed")
def replay_create_pdf_letters(notification_id):
    print("Create task to create_letters_pdf for notification: {}".format(notification_id))
    create_letters_pdf.apply_async([str(notification_id)], queue=QueueNames.CREATE_LETTERS_PDF)


@notify_command(name='replay-service-callbacks')
@click.option('-f', '--file_name', required=True,
              help="""Full path of the file to upload, file is a contains client references of
              notifications that need the status to be sent to the service.""")
@click.option('-s', '--service_id', required=True,
              help="""The service that the callbacks are for""")
def replay_service_callbacks(file_name, service_id):
    print("Start send service callbacks for service: ", service_id)
    errors = []
    notifications = []
    file = open(file_name)

    for ref in file:
        try:
            notification = Notification.query.filter_by(client_reference=ref.strip()).one()
            notifications.append(notification)
        except NoResultFound:
            errors.append("Reference: {} was not found in notifications.".format(ref))

    for e in errors:
        print(e)
    if errors:
        raise Exception("Some notifications for the given references were not found")

    for n in notifications:
        check_for_callback_and_send_delivery_status_to_service(n)

    print("Replay service status for service: {}. Sent {} notification status updates to the queue".format(
        service_id, len(notifications)))


def setup_commands(application):
    application.cli.add_command(command_group)


@notify_command(name='migrate-data-to-ft-billing')
@click.option('-s', '--start_date', required=True, help="start date inclusive", type=click_dt(format='%Y-%m-%d'))
@click.option('-e', '--end_date', required=True, help="end date inclusive", type=click_dt(format='%Y-%m-%d'))
@statsd(namespace="tasks")
def migrate_data_to_ft_billing(start_date, end_date):

    print('Billing migration from date {} to {}'.format(start_date, end_date))

    process_date = start_date
    total_updated = 0

    while process_date < end_date:

        sql = \
            """
            select count(*) from notification_history where notification_status!='technical-failure'
            and key_type!='test'
            and notification_status!='created'
            and created_at >= (date :start + time '00:00:00') at time zone 'Europe/London' at time zone 'UTC'
            and created_at < (date :end + time '00:00:00') at time zone 'Europe/London' at time zone 'UTC'
            """
        num_notifications = db.session.execute(sql, {"start": process_date,
                                                     "end": process_date + timedelta(days=1)}).fetchall()[0][0]
        sql = \
            """
            select count(*) from
            (select distinct service_id, template_id, rate_multiplier,
            sent_by from notification_history
            where notification_status!='technical-failure'
            and key_type!='test'
            and notification_status!='created'
            and created_at >= (date :start + time '00:00:00') at time zone 'Europe/London' at time zone 'UTC'
            and created_at < (date :end + time '00:00:00') at time zone 'Europe/London' at time zone 'UTC'
            ) as distinct_records
            """

        predicted_records = db.session.execute(sql, {"start": process_date,
                                                     "end": process_date + timedelta(days=1)}).fetchall()[0][0]

        start_time = datetime.now()
        print('ft_billing: Migrating date: {}, notifications: {}, expecting {} ft_billing rows'
              .format(process_date.date(), num_notifications, predicted_records))

        # migrate data into ft_billing, ignore if records already exist - do not do upsert
        sql = \
            """
            insert into ft_billing (aet_date, template_id, service_id, notification_type, provider, rate_multiplier,
                international, billable_units, notifications_sent, rate)
                select aet_date, template_id, service_id, notification_type, provider, rate_multiplier, international,
                    sum(billable_units) as billable_units, sum(notifications_sent) as notification_sent,
                    case when notification_type = 'sms' then sms_rate else letter_rate end as rate
                from (
                    select
                        n.id,
                        da.bst_date as aet_date,
                        coalesce(n.template_id, '00000000-0000-0000-0000-000000000000') as template_id,
                        coalesce(n.service_id, '00000000-0000-0000-0000-000000000000') as service_id,
                        n.notification_type,
                        coalesce(n.sent_by, (
                        case
                        when notification_type = 'sms' then
                            coalesce(sent_by, 'unknown')
                        when notification_type = 'letter' then
                            coalesce(sent_by, 'dvla')
                        else
                            coalesce(sent_by, 'smtp')
                        end )) as provider,
                        coalesce(n.rate_multiplier,1) as rate_multiplier,
                        s.crown,
                        coalesce((select rates.rate from rates
                        where n.notification_type = rates.notification_type and n.sent_at > rates.valid_from
                        order by rates.valid_from desc limit 1), 0) as sms_rate,
                        coalesce((select l.rate from letter_rates l where n.rate_multiplier = l.sheet_count
                        and s.crown = l.crown and n.notification_type='letter'), 0) as letter_rate,
                        coalesce(n.international, false) as international,
                        n.billable_units,
                        1 as notifications_sent
                    from public.notification_history n
                    left join templates t on t.id = n.template_id
                    left join dm_datetime da on n.created_at>= da.utc_daytime_start
                        and n.created_at < da.utc_daytime_end
                    left join services s on s.id = n.service_id
                    where n.notification_status!='technical-failure'
                        and n.key_type!='test'
                        and n.notification_status!='created'
                        and n.created_at >= (date :start + time '00:00:00') at time zone 'Europe/London'
                        at time zone 'UTC'
                        and n.created_at < (date :end + time '00:00:00') at time zone 'Europe/London' at time zone 'UTC'
                    ) as individual_record
                group by aet_date, template_id, service_id, notification_type, provider, rate_multiplier, international,
                    sms_rate, letter_rate
                order by aet_date
            on conflict on constraint ft_billing_pkey do update set
             billable_units = excluded.billable_units,
             notifications_sent = excluded.notifications_sent,
             rate = excluded.rate
            """

        result = db.session.execute(sql, {"start": process_date, "end": process_date + timedelta(days=1)})
        db.session.commit()
        print('ft_billing: --- Completed took {}ms. Migrated {} rows.'.format(datetime.now() - start_time,
                                                                              result.rowcount))
        if predicted_records != result.rowcount:
            print('          : ^^^ Result mismatch by {} rows ^^^'
                  .format(predicted_records - result.rowcount))

        process_date += timedelta(days=1)

        total_updated += result.rowcount
    print('Total inserted/updated records = {}'.format(total_updated))


@notify_command()
def list_jobs():
    print_jobs(dao_get_jobs())


@notify_command(name='get-job')
@click.option('-j', '--job_id', required=True, type=click.UUID)
def get_job(job_id):
    job = dao_get_job_by_id(job_id)
    print_jobs([job])


def print_jobs(jobs):
    writer = csv.writer(sys.stdout)
    writer.writerow([
        'job_id',
        'job_status',
        'service_id',
        'service_name',
        'created_at',
        'updated_at',
        'notification_count',
        'notifications_sent',
        'notifications_delivered',
        'notifications_failed',
        'processing_started',
        'processing_finished',
        'processing_time',
        'scheduled_for',
    ])

    for job in jobs:
        processing_time = None

        if job.processing_started is not None and job.processing_finished is not None:
            processing_time = (job.processing_finished - job.processing_started).total_seconds()

        writer.writerow([
            job.id,
            job.job_status,
            job.service.id,
            job.service.name,
            job.created_at,
            job.updated_at,
            job.notification_count,
            job.notifications_sent,
            job.notifications_delivered,
            job.notifications_failed,
            job.processing_started,
            job.processing_finished,
            processing_time,
            job.scheduled_for,
        ])
