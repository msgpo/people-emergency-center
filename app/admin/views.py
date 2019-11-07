from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required
from flask_rq import get_queue

from app import db, os
from app.admin.forms import (
    ChangeAccountTypeForm,
    Clearance1StatusForm,
    Clearance2StatusForm,
    Clearance3StatusForm,
    Clearance4StatusForm,
    ChangeUserEmailForm,
    InviteUserForm,
    NewUserForm,
    DownloadCSVForm
)
from app.decorators import admin_required
from app.email import send_email
from app.models import EditableHTML, Role, User, Volunteer

from .. import csrf
import csv
import io
import json
from datetime import datetime


admin = Blueprint('admin', __name__)


@admin.route('/')
@login_required
@admin_required
def index():
    """Admin dashboard page."""
    return render_template('admin/index.html')

@admin.route('/new-user', methods=['GET', 'POST'])
@login_required
@admin_required
def new_user():
    """Create a new user."""
    form = NewUserForm()
    if form.validate_on_submit():
        user = User(
            role=form.role.data,
            first_name=form.first_name.data,
            last_name=form.last_name.data,
            email=form.email.data,
            password=form.password.data)
        db.session.add(user)
        db.session.commit()
        flash('User {} successfully created'.format(user.full_name()),
              'form-success')
    return render_template('admin/new_user.html', form=form)


@admin.route('/invite-user', methods=['GET', 'POST'])
@login_required
@admin_required
def invite_user():
    """Invites a new user to create an account and set their own password."""
    form = InviteUserForm()
    if form.validate_on_submit():
        user = User(
            role=form.role.data,
            first_name=form.first_name.data,
            last_name=form.last_name.data,
            email=form.email.data)
        db.session.add(user)
        db.session.commit()
        token = user.generate_confirmation_token()
        invite_link = url_for(
            'account.join_from_invite',
            user_id=user.id,
            token=token,
            _external=True)
        get_queue().enqueue(
            send_email,
            recipient=user.email,
            subject='You Are Invited To Join',
            template='account/email/invite',
            user=user,
            invite_link=invite_link,
        )
        flash('User {} successfully invited'.format(user.full_name()),
              'form-success')
    return render_template('admin/new_user.html', form=form)


@admin.route('/users')
@login_required
@admin_required
def registered_users():
    """View all registered users."""
    users = User.query.all()
    roles = Role.query.all()
    return render_template(
        'admin/registered_users.html', users=users, roles=roles)


@admin.route('/user/<int:user_id>')
@admin.route('/user/<int:user_id>/info')
@login_required
@admin_required
def user_info(user_id):
    """View a user's profile."""
    user = User.query.filter_by(id=user_id).first()
    if user is None:
        abort(404)
    return render_template('admin/manage_user.html', user=user)


@admin.route('/user/<int:user_id>/change-email', methods=['GET', 'POST'])
@login_required
@admin_required
def change_user_email(user_id):
    """Change a user's email."""
    user = User.query.filter_by(id=user_id).first()
    if user is None:
        abort(404)
    form = ChangeUserEmailForm()
    if form.validate_on_submit():
        user.email = form.email.data
        db.session.add(user)
        db.session.commit()
        flash('Email for user {} successfully changed to {}.'.format(
            user.full_name(), user.email), 'form-success')
    return render_template('admin/manage_user.html', user=user, form=form)


@admin.route(
    '/user/<int:user_id>/change-account-type', methods=['GET', 'POST'])
@login_required
@admin_required
def change_account_type(user_id):
    """Change a user's account type."""
    if current_user.id == user_id:
        flash('You cannot change the type of your own account. Please ask '
              'another administrator to do this.', 'error')
        return redirect(url_for('admin.user_info', user_id=user_id))

    user = User.query.get(user_id)
    if user is None:
        abort(404)
    form = ChangeAccountTypeForm()
    if form.validate_on_submit():
        user.role = form.role.data
        db.session.add(user)
        db.session.commit()
        flash('Role for user {} successfully changed to {}.'.format(
            user.full_name(), user.role.name), 'form-success')
    return render_template('admin/manage_user.html', user=user, form=form)


@admin.route('/user/<int:user_id>/delete')
@login_required
@admin_required
def delete_user_request(user_id):
    """Request deletion of a user's account."""
    user = User.query.filter_by(id=user_id).first()
    if user is None:
        abort(404)
    return render_template('admin/manage_user.html', user=user)


@admin.route('/user/<int:user_id>/_delete')
@login_required
@admin_required
def delete_user(user_id):
    """Delete a user's account."""
    if current_user.id == user_id:
        flash('You cannot delete your own account. Please ask another '
              'administrator to do this.', 'error')
    else:
        user = User.query.filter_by(id=user_id).first()
        db.session.delete(user)
        db.session.commit()
        flash('Successfully deleted user %s.' % user.full_name(), 'success')
    return redirect(url_for('admin.registered_users'))


@admin.route('/_update_editor_contents', methods=['POST'])
@login_required
@admin_required
def update_editor_contents():
    """Update the contents of an editor."""

    edit_data = request.form.get('edit_data')
    editor_name = request.form.get('editor_name')

    editor_contents = EditableHTML.query.filter_by(
        editor_name=editor_name).first()
    if editor_contents is None:
        editor_contents = EditableHTML(editor_name=editor_name)
    editor_contents.value = edit_data

    db.session.add(editor_contents)
    db.session.commit()

    return 'OK', 200

@admin.route('/view_volunteers', methods=['GET', 'POST'])
@csrf.exempt
@login_required
@admin_required
def view_clearances():
    """View all volunteer clearances."""
    volunteers = Volunteer.query.all()

    """Download CSV with all volunteer information"""
    download_csv_form = DownloadCSVForm()

    if request.method == 'POST':

        """This should automatically set the filepath to your downloads folder.
        Just hardcode a file path for now if it doesn't work though."""
        file_path = file_path = os.path.expanduser('~') + "/Downloads/"

        print("CSV download code here")
        volunteers = Volunteer.query.order_by(Volunteer.id.desc()).all()
        today = datetime.now()
        timestr = today.strftime("%Y%m%d-%H%M%S")
        file_name = "volunteers" + timestr + ".csv"

        with io.open(file_path + file_name, 'w', newline='') as csvfile:

            csv_writer = csv.writer(csvfile)

            csv_writer.writerow(['First Name', 'Last Name', 'Email',
                                 'Phone Number', 'Address Street', 'City', 'State', 'Organization',
                                 'Over 10 years in PA', 'Child Abuse Clearance Status', 'Comment 1',
                                 '(Link) Child Abuse Clearance', '(Date) Child Abuse Clearance',
                                 'Criminal Record Clearance','Comment 2','(Link) Criminal Record Clearance',
                                 '(Date) Criminal Record', 'FBI Background Check', 'Comment 3',
                                 '(Link) FBI Background Check', '(Date) FBI Background Check',
                                 'Volunteer Conflict of Interest','Comment 4', '(Link) Volunteer Conflict of Interest',
                                 '(Date) Volunteer Conflict of Interest'])

            for v in volunteers:
                csv_writer.writerow([
                    v.first_name,
                    v.last_name,
                    v.email,
                    v.phone_number,
                    v.address_street,
                    v.address_city,
                    v.address_state,
                    v.organization,
                    str(v.year_pa),

                    str(v.status1),
                    v.comment1,
                    v.link1,
                    v.date1,

                    str(v.status2),
                    v.comment2,
                    v.link2,
                    v.date2,

                    str(v.status3),
                    v.comment3,
                    v.link3,
                    v.date3,

                    str(v.status4),
                    v.comment4,
                    v.link4,
                    v.date4])

    return render_template('admin/view_clearances.html', volunteers = volunteers, download_csv_form = download_csv_form)

@admin.route('/view_one/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def view_one(id):

    v_entry = Volunteer.query.filter_by(id=id).first()
    v_form1 = Clearance1StatusForm()
    v_form2 = Clearance2StatusForm()
    v_form3 = Clearance3StatusForm()
    v_form4 = Clearance4StatusForm()

    if v_form1.submit_clearance_1.data and v_form1.validate():
        if "submit_clearance_1" in request.form.keys():
            v_entry.status1 = v_form1.new_status_1.data
            v_entry.comment1 = v_form1.comment_1.data
            if "CLEARED" in v_entry.status1.value:
                v_entry.date1 = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
            db.session.commit()

    if v_form2.submit_clearance_2.data and v_form2.validate():
        if "submit_clearance_2" in request.form.keys():
            v_entry.status2 = v_form2.new_status_2.data
            v_entry.comment2 = v_form2.comment_2.data
            if "CLEARED" in v_entry.status2.value:
                v_entry.date2 = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
            db.session.commit()

    if v_form3.submit_clearance_3.data and v_form3.validate():
        if "submit_clearance_3" in request.form.keys():
            v_entry.status3 = v_form3.new_status_3.data
            v_entry.comment3 = v_form3.comment_3.data
            if "CLEARED" in v_entry.status3.value:
                v_entry.date3 = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
            db.session.commit()

    if v_form4.submit_clearance_4.data and v_form4.validate():
        if "submit_clearance_4" in request.form.keys():
            v_entry.status4 = v_form4.new_status_4.data
            v_entry.comment4 = v_form4.comment_4.data
            if "CLEARED" in v_entry.status4.value:
                v_entry.date4 = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
            db.session.commit()

    return render_template('admin/view_one.html', v_entry = v_entry, v_form1 = v_form1, v_form2 = v_form2, v_form3 = v_form3, v_form4 = v_form4)


    



