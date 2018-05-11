import json
from datetime import datetime

from flask import (
    current_app,
    flash,
    redirect,
    render_template,
    session,
    url_for,
)
from itsdangerous import SignatureExpired
from notifications_utils.url_safe_token import check_token

from app import user_api_client
from app.main import main
from app.main.forms import NewPasswordForm
from app.main.views.two_factor import log_in_user

NOTIFY_USER_ID = '6af522d0-2915-4e52-83a3-3690455a5fe6'


@main.route('/new-password/<path:token>', methods=['GET', 'POST'])
def new_password(token):
    try:
        token_data = check_token(token, current_app.config['SECRET_KEY'], current_app.config['DANGEROUS_SALT'],
                                 current_app.config['EMAIL_EXPIRY_SECONDS'])
    except SignatureExpired:
        flash('The link in the email we sent you has expired. Enter your email address to resend.')
        return redirect(url_for('.forgot_password'))

    email_address = json.loads(token_data)['email']
    user = user_api_client.get_user_by_email(email_address)
    if user.password_changed_at and datetime.strptime(user.password_changed_at, '%Y-%m-%d %H:%M:%S.%f') > \
            datetime.strptime(json.loads(token_data)['created_at'], '%Y-%m-%d %H:%M:%S.%f'):
        flash('The link in the email has already been used')
        return redirect(url_for('main.index'))

    form = NewPasswordForm()

    if form.validate_on_submit():
        user_api_client.reset_failed_login_count(user.id)
        session['user_details'] = {
            'id': user.id,
            'email': user.email_address,
            'password': form.new_password.data}

        # TODO: remove this after alpha, when templates are sorted
        if user.id == NOTIFY_USER_ID:
            return log_in_user(user.id)

        if user.auth_type == 'email_auth':
            # they've just clicked an email link, so have done an email auth journey anyway. Just log them in.
            return log_in_user(user.id)
        else:
            # send user a 2fa sms code
            user_api_client.send_verify_code(user.id, 'sms', user.mobile_number)
            return redirect(url_for('main.two_factor'))
    else:
        return render_template('views/new-password.html', token=token, form=form, user=user)
