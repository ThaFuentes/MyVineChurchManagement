# app/routes/auth/views.py
# Full path: MyVineChurch/app/routes/auth/views.py
# File name: views.py
# Brief, detailed purpose: All route handlers (controllers) for the Auth blueprint.
# • Every single @auth_bp.route from the old flat auth.py lives here.
# • 100% original behavior preserved: root redirect, login/logout, full registration (Owner on first user, pending after), password reset, forgot username, server-side censorship on visible fields, form repopulation on error.
# • This is the “HTTP layer” only – thin, readable, easy to grow.
# • Uses modular queries.py, forms.py, and utils.py – no inline SQL, no inline validation.

from flask import render_template, request, redirect, url_for, session, flash
from werkzeug.security import check_password_hash, generate_password_hash

# Package-relative blueprint
from . import auth_bp

# Modular imports
from .queries import (
    get_total_user_count,
    get_user_by_username,
    get_user_by_email,
    create_new_user,
    update_user_password
)
from .forms import (
    validate_register_form,
    validate_password_reset_form,
    validate_forgot_username_form
)
from .utils import generate_reset_code

from app.models.log import log_change
from app.utils.emailer import send_email


# ----------------------------------------------------------------------
# Root Route (Landing Page) – smart redirect
# ----------------------------------------------------------------------
@auth_bp.route('/')
def index():
    """
    Smart root: logged-in users → private dashboard, guests → public dashboard.
    """
    if session.get('user_id'):
        return redirect(url_for('dashboard.dashboard'))
    return redirect(url_for('public.public_dashboard'))


# ----------------------------------------------------------------------
# Login
# ----------------------------------------------------------------------
@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        if not username or not password:
            flash('Please enter both username and password.', 'error')
            return render_template('auth/login.html')

        user = get_user_by_username(username)
        if not user:
            flash('Invalid credentials.', 'error')
            return render_template('auth/login.html')

        if user['role'] == 'pending':
            flash('Your account is pending approval.', 'info')
            return render_template('auth/login.html')

        if user['role'] == 'banned':
            flash('Your account has been banned.', 'error')
            return render_template('auth/login.html')

        if check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['user_role'] = user['role']
            log_change(user['id'], 'login', change_details='User logged in.')
            return redirect(url_for('dashboard.dashboard'))
        else:
            flash('Invalid credentials.', 'error')

    return render_template('auth/login.html')


# ----------------------------------------------------------------------
# Logout
# ----------------------------------------------------------------------
@auth_bp.route('/logout')
def logout():
    user_id = session.get('user_id')
    if user_id:
        log_change(user_id, 'logout', change_details='User logged out.')
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('public.public_dashboard'))


# ----------------------------------------------------------------------
# Register
# ----------------------------------------------------------------------
@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    total_users = get_total_user_count()
    is_first_user = (total_users == 0)

    if request.method == 'POST':
        clean_data = validate_register_form(request.form)
        if not clean_data:
            # Repopulate form on error
            return render_template('auth/register.html',
                                   is_first_user=is_first_user,
                                   form=request.form)

        hashed_pw = generate_password_hash(clean_data['password'])
        role = 'Owner' if is_first_user else 'pending'
        needs_approval = 0 if is_first_user else 1

        try:
            new_id = create_new_user(
                first_name=clean_data['first_name'],
                last_name=clean_data['last_name'],
                email=clean_data['email'],
                phone=clean_data['phone'],
                address=clean_data['address'],
                birthday=clean_data['birthday'],
                username=clean_data['username'],
                hashed_password=hashed_pw,
                role=role,
                needs_approval=needs_approval,
                accepts_emails=clean_data['accepts_emails'],
                show_birthday=clean_data['show_birthday']
            )

            log_change(new_id, 'register', change_details=f"User {clean_data['username']} registered.")
            flash('Registration successful. Please log in.', 'success')
            return redirect(url_for('auth.login'))

        except Exception:
            flash('Username or Email already exists.', 'error')
            return render_template('auth/register.html',
                                   is_first_user=is_first_user,
                                   form=request.form)

    return render_template('auth/register.html', is_first_user=is_first_user)


# ----------------------------------------------------------------------
# Request Password Reset
# ----------------------------------------------------------------------
@auth_bp.route('/request-reset-password', methods=['GET', 'POST'])
def request_reset_password():
    if request.method == 'POST':
        email = validate_password_reset_form(request.form)
        if not email:
            return render_template('auth/request_reset_password.html')

        user = get_user_by_email(email)
        if user:
            reset_code = generate_reset_code()
            hashed_code = generate_password_hash(reset_code)

            try:
                update_user_password(user['id'], hashed_code)
                send_email(email, 'Password Reset - MyVineChurch.Online',
                           f'Your temporary password reset code is: {reset_code}\n\n'
                           f'Log in with this code and change your password immediately.')
                flash('Reset code sent to your email.', 'success')
            except Exception:
                flash('Email send failed. Contact admin.', 'error')
        else:
            flash('If the email exists, a reset code has been sent.', 'info')

        return redirect(url_for('auth.login'))

    return render_template('auth/request_reset_password.html')


# ----------------------------------------------------------------------
# Forgot Username
# ----------------------------------------------------------------------
@auth_bp.route('/forgot-username', methods=['GET', 'POST'])
def forgot_username():
    if request.method == 'POST':
        email = validate_forgot_username_form(request.form)
        if not email:
            return render_template('auth/forgot_username.html')

        user = get_user_by_email(email)
        if user:
            try:
                send_email(email, 'Username Recovery - MyVineChurch.Online',
                           f'Your username is: {user["username"]}')
                flash('Username sent to your email.', 'success')
            except Exception:
                flash('Email send failed. Contact admin.', 'error')
        else:
            flash('If the email exists, your username has been sent.', 'info')

        return redirect(url_for('auth.login'))

    return render_template('auth/forgot_username.html')