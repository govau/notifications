from flask import render_template, url_for
from flask_login import login_required
from werkzeug.utils import redirect

from app import provider_client
from app.main import main
from app.main.forms import ProviderForm
from app.utils import user_is_platform_admin


@main.route("/providers")
@login_required
@user_is_platform_admin
def view_providers():
    providers = provider_client.get_all_providers()['provider_details']
    domestic_email_providers, domestic_sms_providers, intl_sms_providers = [], [], []
    for provider in providers:
        if provider['notification_type'] == 'sms':
            domestic_sms_providers.append(provider)
            if provider.get('supports_international', None):
                intl_sms_providers.append(provider)
        elif provider['notification_type'] == 'email':
            domestic_email_providers.append(provider)

    return render_template(
        'views/providers/providers.html',
        email_providers=domestic_email_providers,
        domestic_sms_providers=domestic_sms_providers,
        intl_sms_providers=intl_sms_providers
    )


@main.route("/provider/<provider_id>/edit", methods=['GET', 'POST'])
@login_required
@user_is_platform_admin
def edit_provider(provider_id):
    provider = provider_client.get_provider_by_id(provider_id)['provider_details']
    form = ProviderForm(
        priority=provider['priority'],
        active=provider['active'],
        supports_international=provider['supports_international'],
    )

    if form.validate_on_submit():
        provider_client.update_provider(
            provider_id,
            form.priority.data,
            active=form.active.data,
            supports_international=form.supports_international.data
        )
        return redirect(url_for('.view_providers'))

    return render_template('views/providers/edit-provider.html', form=form, provider=provider)


@main.route("/provider/<provider_id>")
@login_required
@user_is_platform_admin
def view_provider(provider_id):
    versions = provider_client.get_provider_versions(provider_id)
    return render_template('views/providers/provider.html', provider_versions=versions['data'])
