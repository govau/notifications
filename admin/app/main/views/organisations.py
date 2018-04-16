from flask import flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required
from notifications_python_client.errors import HTTPError
from werkzeug.exceptions import abort

from app import (
    current_organisation,
    org_invite_api_client,
    organisations_client,
    user_api_client,
)
from app.main import main
from app.main.forms import (
    ConfirmPasswordForm,
    CreateOrUpdateOrganisation,
    InviteOrgUserForm,
    RenameOrganisationForm,
    SearchUsersForm,
)
from app.utils import user_has_permissions, user_is_platform_admin


@main.route("/organisations", methods=['GET'])
@login_required
@user_is_platform_admin
def organisations():
    orgs = organisations_client.get_organisations()

    return render_template(
        'views/organisations/index.html',
        organisations=orgs
    )


@main.route("/organisations/add", methods=['GET', 'POST'])
@login_required
@user_is_platform_admin
def add_organisation():
    form = CreateOrUpdateOrganisation()

    if form.validate_on_submit():
        organisations_client.create_organisation(
            name=form.name.data,
        )

        return redirect(url_for('.organisations'))

    return render_template(
        'views/organisations/add-organisation.html',
        form=form
    )


@main.route("/organisations/<org_id>", methods=['GET'])
@login_required
@user_has_permissions()
def organisation_dashboard(org_id):
    organisation_services = organisations_client.get_organisation_services(org_id)
    for service in organisation_services:
        has_permission = current_user.has_permission_for_service(service['id'], 'view_activity')
        service.update({'has_permission_to_view': has_permission})

    return render_template(
        'views/organisations/organisation/index.html',
        organisation_services=organisation_services
    )


@main.route("/organisations/<org_id>/users", methods=['GET'])
@login_required
@user_has_permissions()
def manage_org_users(org_id):
    users = sorted(
        user_api_client.get_users_for_organisation(org_id=org_id) + [
            invite for invite in org_invite_api_client.get_invites_for_organisation(org_id=org_id)
            if invite.status != 'accepted'
        ],
        key=lambda user: user.email_address,
    )

    return render_template(
        'views/organisations/organisation/users/index.html',
        users=users,
        show_search_box=(len(users) > 7),
        form=SearchUsersForm(),
    )


@main.route("/organisations/<org_id>/users/invite", methods=['GET', 'POST'])
@login_required
@user_has_permissions()
def invite_org_user(org_id):
    form = InviteOrgUserForm(
        invalid_email_address=current_user.email_address
    )
    if form.validate_on_submit():
        email_address = form.email_address.data
        invited_org_user = org_invite_api_client.create_invite(
            current_user.id,
            org_id,
            email_address
        )

        flash('Invite sent to {}'.format(invited_org_user.email_address), 'default_with_tick')
        return redirect(url_for('.manage_org_users', org_id=org_id))

    return render_template(
        'views/organisations/organisation/users/invite-org-user.html',
        form=form
    )


@main.route("/organisations/<org_id>/users/<user_id>", methods=['GET', 'POST'])
@login_required
@user_has_permissions()
def edit_user_org_permissions(org_id, user_id):
    user = user_api_client.get_user(user_id)

    return render_template(
        'views/organisations/organisation/users/user/index.html',
        user=user
    )


@main.route("/organisations/<org_id>/users/<user_id>/delete", methods=['GET', 'POST'])
@login_required
@user_has_permissions()
def remove_user_from_organisation(org_id, user_id):
    user = user_api_client.get_user(user_id)
    if request.method == 'POST':
        try:
            organisations_client.remove_user_from_organisation(org_id, user_id)
        except HTTPError as e:
            msg = "You cannot remove the only user for a service"
            if e.status_code == 400 and msg in e.message:
                flash(msg, 'info')
                return redirect(url_for(
                    '.manage_org_users',
                    org_id=org_id))
            else:
                abort(500, e)

        return redirect(url_for(
            '.manage_org_users',
            org_id=org_id
        ))

    flash('Are you sure you want to remove {}?'.format(user.name), 'remove')
    return render_template(
        'views/organisations/organisation/users/user/index.html',
        user=user,
    )


@main.route("/organisations/<org_id>/cancel-invited-user/<invited_user_id>", methods=['GET'])
@login_required
@user_has_permissions()
def cancel_invited_org_user(org_id, invited_user_id):
    org_invite_api_client.cancel_invited_user(org_id=org_id, invited_user_id=invited_user_id)

    return redirect(url_for('main.manage_org_users', org_id=org_id))


@main.route("/organisations/<org_id>/settings/", methods=['GET'])
@login_required
@user_has_permissions()
def organisation_settings(org_id):
    return render_template(
        'views/organisations/organisation/settings/index.html',
    )


@main.route("/organisations/<org_id>/settings/edit-name", methods=['GET', 'POST'])
@login_required
@user_has_permissions()
def edit_organisation_name(org_id):
    form = RenameOrganisationForm()

    if request.method == 'GET':
        form.name.data = current_organisation.get('name')

    if form.validate_on_submit():
        unique_name = organisations_client.is_organisation_name_unique(org_id, form.name.data)
        if not unique_name:
            form.name.errors.append("This organisation name is already in use")
            return render_template('views/organisations/organisation/settings/edit-name/index.html', form=form)
        session['organisation_name_change'] = form.name.data
        return redirect(url_for('.confirm_edit_organisation_name', org_id=org_id))

    return render_template(
        'views/organisations/organisation/settings/edit-name/index.html',
        form=form,
    )


@main.route("/organisations/<org_id>/settings/edit-name/confirm", methods=['GET', 'POST'])
@login_required
@user_has_permissions()
def confirm_edit_organisation_name(org_id):
    # Validate password for form
    def _check_password(pwd):
        return user_api_client.verify_password(current_user.id, pwd)

    form = ConfirmPasswordForm(_check_password)

    if form.validate_on_submit():
        try:
            organisations_client.update_organisation_name(
                current_organisation['id'],
                name=session['organisation_name_change'],
            )
        except HTTPError as e:
            error_msg = "Organisation name already exists"
            if e.status_code == 400 and error_msg in e.message:
                # Redirect the user back to the change service name screen
                flash('This organisation name is already in use', 'error')
                return redirect(url_for('main.edit_organisation_name', org_id=org_id))
            else:
                raise e
        else:
            session.pop('organisation_name_change')
            return redirect(url_for('.organisation_settings', org_id=org_id))
    return render_template(
        'views/organisations/organisation/settings/edit-name/confirm.html',
        new_name=session['organisation_name_change'],
        form=form)
