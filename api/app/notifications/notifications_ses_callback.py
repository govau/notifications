from datetime import datetime, timedelta
import iso8601

from flask import (
    Blueprint,
    request,
    current_app,
    json,
    jsonify,
)
from sqlalchemy.orm.exc import NoResultFound

from app import statsd_client
from app.clients.email.aws_ses import get_aws_responses
from app.dao import notifications_dao
from app.dao.complaint_dao import save_complaint
from app.dao.notifications_dao import dao_get_notification_history_by_reference
from app.dao.service_callback_api_dao import (
    get_service_delivery_status_callback_api_for_service, get_service_complaint_callback_api_for_service
)
from app.models import Complaint
from app.models import NOTIFICATION_SENDING, NOTIFICATION_PENDING
from app.notifications.utils import autoconfirm_subscription
from app.celery.service_callback_tasks import (
    send_delivery_status_to_service,
    send_complaint_to_service,
    create_delivery_status_callback_data,
    create_complaint_callback_data
)
from app.config import QueueNames
from app.errors import (
    register_errors,
    InvalidRequest
)

ses_callback_blueprint = Blueprint('notifications_ses_callback', __name__)

register_errors(ses_callback_blueprint)


@ses_callback_blueprint.route('/notifications/email/ses', methods=['POST'])
def sns_callback_handler():
    req_json = request.get_json(force=True)

    if autoconfirm_subscription(req_json):
        return jsonify(
            result="success", message="SES-SNS auto-confirm callback succeeded"
        ), 200

    ok, retry = process_ses_results(req_json)

    if ok:
        return jsonify(
            result="success", message="SES-SNS callback succeeded"
        ), 200

    if retry:
        # 500 counts as a failed delivery attempt so SNS will retry.
        # See https://docs.aws.amazon.com/sns/latest/dg/DeliveryPolicies.html#DeliveryPolicies
        raise InvalidRequest("SES callback failed, should retry", 500)

    # 400 counts as a permanent failure so SNS will not retry.
    # See https://docs.aws.amazon.com/sns/latest/dg/DeliveryPolicies.html#DeliveryPolicies
    raise InvalidRequest("SES-SNS callback failed", 400)


def process_ses_results(response):
    try:
        ses_message = json.loads(response['Message'])
        notification_type = ses_message['notificationType']

        if notification_type == 'Bounce':
            notification_type = determine_notification_bounce_type(notification_type, ses_message)
        elif notification_type == 'Complaint':
            _check_and_queue_complaint_callback_task(*handle_complaint(ses_message))
            return True, False

        aws_response_dict = get_aws_responses(notification_type)

        notification_status = aws_response_dict['notification_status']
        reference = ses_message['mail']['messageId']

        try:
            notification = notifications_dao.dao_get_notification_by_reference(reference)
        except NoResultFound:
            message_time = iso8601.parse_date(ses_message['mail']['timestamp']).replace(tzinfo=None)
            if datetime.utcnow() - message_time < timedelta(minutes=5):
                return None, True

            current_app.logger.warning(
                "notification not found for reference: {} (update to {})".format(reference, notification_status)
            )
            return None, False

        if notification.status not in {NOTIFICATION_SENDING, NOTIFICATION_PENDING}:
            notifications_dao._duplicate_update_warning(notification, notification_status)
            return None, False

        notifications_dao._update_notification_status(notification=notification, status=notification_status)

        if not aws_response_dict['success']:
            current_app.logger.info(
                "SES delivery failed: notification id {} and reference {} has error found. Status {}".format(
                    notification.id, reference, aws_response_dict['message']
                )
            )
        else:
            current_app.logger.info('SES callback returned status of {} for notification: {}'.format(
                notification_status, notification.id
            ))

        statsd_client.incr('callback.ses.{}'.format(notification_status))

        if notification.sent_at:
            statsd_client.timing_with_dates('callback.ses.elapsed-time', datetime.utcnow(), notification.sent_at)

        _check_and_queue_callback_task(notification)

        return True, False
    except Exception as e:
        current_app.logger.exception('Error processing SES results: {}'.format(type(e)))
        return None, True


def determine_notification_bounce_type(notification_type, ses_message):
    remove_emails_from_bounce(ses_message)
    current_app.logger.info('SES bounce dict: {}'.format(ses_message))
    if ses_message['bounce']['bounceType'] == 'Permanent':
        notification_type = ses_message['bounce']['bounceType']  # permanent or not
    else:
        notification_type = 'Temporary'
    return notification_type


def handle_complaint(ses_message):
    recipient_email = remove_emails_from_complaint(ses_message)[0]
    current_app.logger.info("Complaint from SES: \n{}".format(ses_message))
    try:
        reference = ses_message['mail']['messageId']
    except KeyError as e:
        current_app.logger.exception("Complaint from SES failed to get reference from message", e)
        return
    notification = dao_get_notification_history_by_reference(reference)
    ses_complaint = ses_message.get('complaint', None)

    complaint = Complaint(
        notification_id=notification.id,
        service_id=notification.service_id,
        # TODO: this ID is unique, we should make it a unique index so we don't
        # store duplicate complaints.
        # See https://docs.aws.amazon.com/ses/latest/DeveloperGuide/notification-contents.html#complaint-object
        ses_feedback_id=ses_complaint.get('feedbackId', None) if ses_complaint else None,
        complaint_type=ses_complaint.get('complaintFeedbackType', None) if ses_complaint else None,
        complaint_date=ses_complaint.get('timestamp', None) if ses_complaint else None
    )
    save_complaint(complaint)
    return complaint, notification, recipient_email


def remove_mail_headers(dict_to_edit):
    if dict_to_edit['mail'].get('headers'):
        dict_to_edit['mail'].pop('headers')
    if dict_to_edit['mail'].get('commonHeaders'):
        dict_to_edit['mail'].pop('commonHeaders')


def remove_emails_from_bounce(bounce_dict):
    remove_mail_headers(bounce_dict)
    bounce_dict['mail'].pop('destination')
    bounce_dict['bounce'].pop('bouncedRecipients')


def remove_emails_from_complaint(complaint_dict):
    remove_mail_headers(complaint_dict)
    complaint_dict['complaint'].pop('complainedRecipients')
    return complaint_dict['mail'].pop('destination')


def _check_and_queue_callback_task(notification):
    # queue callback task only if the service_callback_api exists
    service_callback_api = get_service_delivery_status_callback_api_for_service(service_id=notification.service_id)
    if service_callback_api:
        notification_data = create_delivery_status_callback_data(notification, service_callback_api)
        send_delivery_status_to_service.apply_async([str(notification.id), notification_data],
                                                    queue=QueueNames.CALLBACKS)


def _check_and_queue_complaint_callback_task(complaint, notification, recipient):
    # queue callback task only if the service_callback_api exists
    service_callback_api = get_service_complaint_callback_api_for_service(service_id=notification.service_id)
    if service_callback_api:
        complaint_data = create_complaint_callback_data(complaint, notification, service_callback_api, recipient)
        send_complaint_to_service.apply_async([complaint_data], queue=QueueNames.CALLBACKS)
