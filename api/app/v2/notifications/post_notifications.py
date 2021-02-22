import base64
import functools
import io
import math

from flask import request, jsonify, current_app, abort
from notifications_utils.pdf import pdf_page_count, PdfReadError
from notifications_utils.recipients import try_validate_and_format_phone_number

from app import api_user, authenticated_service, notify_celery
from app.config import QueueNames, TaskNames
from app.dao.notifications_dao import dao_update_notification, update_notification_status_by_reference
from app.dao.templates_dao import dao_create_template
from app.dao.users_dao import get_user_by_id
from app.dao.batches_dao import dao_create_batch
from app.letters.utils import upload_letter_pdf
from app.models import (
    Template,
    SMS_TYPE,
    EMAIL_TYPE,
    LETTER_TYPE,
    PRECOMPILED_LETTER,
    PRIORITY,
    KEY_TYPE_TEST,
    KEY_TYPE_TEAM,
    NOTIFICATION_CREATED,
    NOTIFICATION_SENDING,
    NOTIFICATION_DELIVERED,
    NOTIFICATION_PENDING_VIRUS_CHECK,
)
from app.celery.letters_pdf_tasks import create_letters_pdf
from app.celery.research_mode_tasks import create_fake_letter_response_file
from app.notifications.process_notifications import (
    prepare_notification,
    store_notification,
    store_notifications,
    send_notification_to_queue,
    send_notifications_to_queue,
    simulated_recipient,
    get_scheduled_datetime,
)
from app.notifications.process_letter_notifications import (
    create_letter_notification
)
from app.notifications.validators import (
    validate_and_format_recipient,
    check_rate_limiting,
    check_service_can_schedule_notification,
    check_service_has_permission,
    validate_template,
    validate_template_without_content,
    check_service_email_reply_to_id,
    check_service_sms_sender_id
)
from app.schema_validation import validate
from app.v2.errors import BadRequestError
from app.v2.notifications import v2_notification_blueprint
from app.v2.notifications.notification_schemas import (
    post_sms_request,
    post_email_request,
    post_letter_request,
    post_precompiled_letter_request,
    post_batch_request
)
from app.schemas import batch_schema
from app.v2.notifications.create_response import (
    create_post_sms_response_from_notification,
    create_post_email_response_from_notification,
    create_post_letter_response_from_notification,
    create_batch_response_from_batch,
)


@v2_notification_blueprint.route('/{}'.format(LETTER_TYPE), methods=['POST'])
def post_precompiled_letter_notification():
    if 'content' not in (request.get_json() or {}):
        return post_notification(LETTER_TYPE)

    form = validate(request.get_json(), post_precompiled_letter_request)

    # Check both permission to send letters and permission to send pre-compiled PDFs
    check_service_has_permission(LETTER_TYPE, authenticated_service.permissions)
    check_service_has_permission(PRECOMPILED_LETTER, authenticated_service.permissions)

    check_rate_limiting(authenticated_service, api_user)

    template = get_precompiled_letter_template(authenticated_service.id)

    form['personalisation'] = {
        'address_line_1': form['reference']
    }

    reply_to = get_reply_to_text(LETTER_TYPE, form, template)

    notification = process_letter_notification(
        letter_data=form,
        api_key=api_user,
        template=template,
        reply_to_text=reply_to,
        precompiled=True
    )

    resp = {
        'id': notification.id,
        'reference': notification.client_reference
    }

    return jsonify(resp), 201


@v2_notification_blueprint.route('/batch', methods=['POST'])
def send_batch_notifications():
    form = validate(request.json, post_batch_request)
    notification_type = form.get('notification_type')
    check_service_has_permission(notification_type, authenticated_service.permissions)
    check_rate_limiting(authenticated_service, api_user)
    template = validate_template_without_content(
        form['template_id'],
        authenticated_service,
        notification_type,
    )

    notification_requests = form.get('notifications', [])
    batch_params = {
        'client_reference': form.get('reference'),
        'service': authenticated_service.id,
        'template': template.id,
        'template_version': template.version,
        'api_key': api_user.id,
        'api_key_type': api_user.key_type,
    }
    batch = batch_schema.load(batch_params).data
    dao_create_batch(batch)

    def prepare_notifications(requests):
        for notification_request in requests:
            reply_to = get_reply_to_text(notification_type, notification_request, template)

            fallback_params = {
                param: notification_request.get(param, form.get(param))
                for param
                in ['status_callback_url', 'status_callback_bearer_token']
            }

            params = {
                'reference': notification_request.get('reference'),
                'phone_number': notification_request.get('phone_number'),
                'email_address': notification_request.get('email_address'),
                'personalisation': notification_request.get('personalisation'),
                'status_callback_url': notification_request.get('status_callback_url'),
                **fallback_params
            }

            yield prepare_sms_or_email_notification(
                form=params,
                notification_type=notification_type,
                api_key=api_user,
                template=template,
                service=authenticated_service,
                reply_to_text=reply_to,
                batch=batch
            )

    notifications = store_notifications(prepare_notifications(notification_requests))
    send_notifications_to_queue(notifications, research_mode=authenticated_service.research_mode)

    response = create_batch_response_from_batch(batch, url_root=request.url_root)
    return jsonify(response), 201


@v2_notification_blueprint.route('/<notification_type>', methods=['POST'])
def post_notification(notification_type):
    if notification_type == EMAIL_TYPE:
        form = validate(request.get_json(), post_email_request)
    elif notification_type == SMS_TYPE:
        form = validate(request.get_json(), post_sms_request)
    elif notification_type == LETTER_TYPE:
        form = validate(request.get_json(), post_letter_request)
    else:
        abort(404)

    check_service_has_permission(notification_type, authenticated_service.permissions)

    scheduled_for = form.get("scheduled_for", None)

    check_service_can_schedule_notification(authenticated_service.permissions, scheduled_for)

    check_rate_limiting(authenticated_service, api_user)

    template, template_with_content = validate_template(
        form['template_id'],
        form.get('personalisation', {}),
        authenticated_service,
        notification_type,
    )

    reply_to = get_reply_to_text(notification_type, form, template)

    if notification_type == LETTER_TYPE:
        notification = process_letter_notification(
            letter_data=form,
            api_key=api_user,
            template=template,
            reply_to_text=reply_to
        )
    else:
        notification = process_sms_or_email_notification(
            form=form,
            notification_type=notification_type,
            api_key=api_user,
            template=template,
            service=authenticated_service,
            reply_to_text=reply_to
        )

    if notification_type == SMS_TYPE:
        create_resp_partial = functools.partial(
            create_post_sms_response_from_notification,
            from_number=reply_to
        )
    elif notification_type == EMAIL_TYPE:
        create_resp_partial = functools.partial(
            create_post_email_response_from_notification,
            subject=template_with_content.subject,
            email_from='{}@{}'.format(authenticated_service.email_from, current_app.config['NOTIFY_EMAIL_DOMAIN'])
        )
    elif notification_type == LETTER_TYPE:
        create_resp_partial = functools.partial(
            create_post_letter_response_from_notification,
            subject=template_with_content.subject,
        )

    resp = create_resp_partial(
        notification=notification,
        content=str(template_with_content),
        url_root=request.url_root,
        scheduled_for=scheduled_for
    )
    return jsonify(resp), 201


def prepare_sms_or_email_notification(
        *, form, notification_type, api_key,
        template, service, batch=None, reply_to_text=None):

    form_send_to = form['email_address'] if notification_type == EMAIL_TYPE else form['phone_number']
    notification = prepare_notification(
        template_id=template.id,
        template_version=template.version,
        recipient=form_send_to,
        service=service,
        personalisation=form.get('personalisation', None),
        notification_type=notification_type,
        api_key_id=api_key.id,
        key_type=api_key.key_type,
        client_reference=form.get('reference', None),
        reply_to_text=reply_to_text,
        status_callback_url=form.get('status_callback_url', None),
        status_callback_bearer_token=form.get('status_callback_bearer_token', None),
        batch_id=batch.id if batch else None
    )

    return notification


def process_sms_or_email_notification(
        *, form, notification_type, api_key,
        template, service, reply_to_text=None):
    notification = prepare_sms_or_email_notification(
        form=form,
        notification_type=notification_type,
        api_key=api_key,
        template=template,
        service=service,
        reply_to_text=reply_to_text
    )

    # Do not persist or send notification to the queue if it is a simulated recipient
    is_simulated = is_simulated_recipient(
        send_to=notification.to,
        key_type=api_key.key_type,
        service=service,
        notification_type=notification_type
    )
    if is_simulated:
        current_app.logger.debug("POST simulated notification for id: {}".format(notification.id))
        return notification

    scheduled_for = form.get("scheduled_for", None)
    scheduled_for_datetime = get_scheduled_datetime(scheduled_for) if scheduled_for else None
    notification = store_notification(notification, scheduled_for=scheduled_for_datetime)

    # let a periodic process deal with scheduled notifications later
    if scheduled_for_datetime:
        return notification

    queue_name = QueueNames.PRIORITY if template.process_type == PRIORITY else None
    send_notification_to_queue(
        notification=notification,
        research_mode=service.research_mode,
        queue=queue_name
    )
    return notification


def process_letter_notification(*, letter_data, api_key, template, reply_to_text, precompiled=False):
    if api_key.key_type == KEY_TYPE_TEAM:
        raise BadRequestError(message='Cannot send letters with a team api key', status_code=403)

    if not api_key.service.research_mode and api_key.service.restricted and api_key.key_type != KEY_TYPE_TEST:
        raise BadRequestError(message='Cannot send letters when service is in trial mode', status_code=403)

    if precompiled:
        return process_precompiled_letter_notifications(letter_data=letter_data,
                                                        api_key=api_key,
                                                        template=template,
                                                        reply_to_text=reply_to_text)

    should_send = not (api_key.key_type == KEY_TYPE_TEST)

    # if we don't want to actually send the letter, then start it off in SENDING so we don't pick it up
    status = NOTIFICATION_CREATED if should_send else NOTIFICATION_SENDING

    notification = create_letter_notification(letter_data=letter_data,
                                              template=template,
                                              api_key=api_key,
                                              status=status,
                                              reply_to_text=reply_to_text)

    if should_send:
        create_letters_pdf.apply_async(
            [str(notification.id)],
            queue=QueueNames.CREATE_LETTERS_PDF
        )
    elif current_app.config['NOTIFY_ENVIRONMENT'] in ['preview', 'development']:
        create_fake_letter_response_file.apply_async(
            (notification.reference,),
            queue=QueueNames.RESEARCH_MODE
        )
    else:
        update_notification_status_by_reference(notification.reference, NOTIFICATION_DELIVERED)

    return notification


def process_precompiled_letter_notifications(*, letter_data, api_key, template, reply_to_text):
    try:
        status = NOTIFICATION_PENDING_VIRUS_CHECK
        letter_content = base64.b64decode(letter_data['content'])
        pages = pdf_page_count(io.BytesIO(letter_content))
    except ValueError:
        raise BadRequestError(message='Cannot decode letter content (invalid base64 encoding)', status_code=400)
    except PdfReadError:
        current_app.logger.exception(msg='Invalid PDF received')
        raise BadRequestError(message='Letter content is not a valid PDF', status_code=400)

    notification = create_letter_notification(letter_data=letter_data,
                                              template=template,
                                              api_key=api_key,
                                              status=status,
                                              reply_to_text=reply_to_text)

    filename = upload_letter_pdf(notification, letter_content, precompiled=True)
    pages_per_sheet = 2
    notification.billable_units = math.ceil(pages / pages_per_sheet)

    dao_update_notification(notification)

    current_app.logger.info('Calling task scan-file for {}'.format(filename))

    # call task to add the filename to anti virus queue
    notify_celery.send_task(
        name=TaskNames.SCAN_FILE,
        kwargs={'filename': filename},
        queue=QueueNames.ANTIVIRUS,
    )

    return notification


def get_reply_to_text(notification_type, form, template):
    reply_to = None
    if notification_type == EMAIL_TYPE:
        service_email_reply_to_id = form.get("email_reply_to_id", None)
        reply_to = check_service_email_reply_to_id(
            str(authenticated_service.id), service_email_reply_to_id, notification_type
        ) or template.get_reply_to_text()

    elif notification_type == SMS_TYPE:
        service_sms_sender_id = form.get("sms_sender_id", None)
        sms_sender_id = check_service_sms_sender_id(
            str(authenticated_service.id), service_sms_sender_id, notification_type
        )
        if sms_sender_id:
            reply_to = try_validate_and_format_phone_number(sms_sender_id)
        else:
            reply_to = template.get_reply_to_text()

    elif notification_type == LETTER_TYPE:
        reply_to = template.get_reply_to_text()

    return reply_to


def get_precompiled_letter_template(service_id):
    template = Template.query.filter_by(
        service_id=service_id,
        template_type=LETTER_TYPE,
        hidden=True
    ).first()
    if template is not None:
        return template

    template = Template(
        name='Pre-compiled PDF',
        created_by=get_user_by_id(current_app.config['NOTIFY_USER_ID']),
        service_id=service_id,
        template_type=LETTER_TYPE,
        hidden=True,
        subject='Pre-compiled PDF',
        content='',
    )

    dao_create_template(template)

    return template


def is_simulated_recipient(*, send_to, key_type, service, notification_type):
    target = validate_and_format_recipient(
        send_to=send_to,
        key_type=key_type,
        service=service,
        notification_type=notification_type
    )

    return simulated_recipient(target, notification_type)
