from flask import render_template
from flask_login import login_required

from app import inbound_number_client
from app.main import main
from app.utils import user_is_platform_admin


@main.route('/inbound-sms-admin', methods=['GET', 'POST'])
@login_required
@user_is_platform_admin
def inbound_sms_admin():
    data = inbound_number_client.get_all_inbound_sms_number_service()

    return render_template('views/inbound-sms-admin.html', inbound_num_list=data)
