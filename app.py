from flask import Flask, render_template, request, redirect, url_for, flash, session, g
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import os

from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash


def create_app(test_config=None):
    """Factory pattern for creating the Flask application.

    The factory allows us to create multiple instances of the app with
    different configurations for testing or development. If `test_config`
    is provided it will override the default settings.
    """
    app = Flask(__name__)

    # Basic configuration
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'change-me')
    # Use a local SQLite database by default
    db_path = os.path.join(app.root_path, 'crm.db')
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
        'DATABASE_URL', f'sqlite:///{db_path}'
    )
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    if test_config is not None:
        # Load any test configuration passed in
        app.config.update(test_config)

    # Initialize the database
    db.init_app(app)

    # Provide the datetime class to templates so we can display the current year
    @app.context_processor
    def inject_now():
        return {'datetime': datetime}

    # Load the logged-in user on every request
    @app.before_request
    def load_logged_in_user():
        user_id = session.get('user_id')
        if user_id is None:
            g.user = None
        else:
            g.user = User.query.get(user_id)

    # Create tables and an initial master user if none exist
    with app.app_context():
        db.create_all()
        if User.query.first() is None:
            # Create a default master user; instruct the client to change the password
            default_master = User(username='admin', role='master')
            default_master.set_password('admin123')
            db.session.add(default_master)
            db.session.commit()

    # Register routes
    register_routes(app)

    return app


db = SQLAlchemy()


class Contact(db.Model):
    """Stores basic information about a person or organization that the sales
    team might interact with. A contact can be a lead, prospect or existing
    customer."""

    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(120), nullable=False)
    last_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False)
    phone = db.Column(db.String(50), nullable=True)
    company = db.Column(db.String(255), nullable=True)
    address = db.Column(db.String(255), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    messages = db.relationship('Message', backref='contact', lazy=True)

    # Sales pipeline fields
    #
    # potential_spend:
    #     Represents the total dollar value of open quotes or proposals.
    # accepted_spend:
    #     Represents the dollar value of quotes that have been accepted by the customer.
    # billed_amount:
    #     Total amount invoiced to the customer.
    # received_amount:
    #     Total payments received from the customer.
    # rating:
    #     A subjective score (1–10) estimating likelihood of repeat business.
    potential_spend = db.Column(db.Float, default=0.0)
    accepted_spend = db.Column(db.Float, default=0.0)
    billed_amount = db.Column(db.Float, default=0.0)
    received_amount = db.Column(db.Float, default=0.0)
    rating = db.Column(db.Integer, default=0)

    def __repr__(self):
        return f'<Contact {self.first_name} {self.last_name}>'


class Message(db.Model):
    """Logs every outbound communication to a contact. Keeping a history of
    messages helps the team track interactions and pick up conversations
    context."""

    id = db.Column(db.Integer, primary_key=True)
    contact_id = db.Column(db.Integer, db.ForeignKey('contact.id'), nullable=False)
    channel = db.Column(db.String(10), nullable=False)  # email or sms
    subject = db.Column(db.String(255), nullable=True)
    body = db.Column(db.Text, nullable=False)
    sent_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<Message {self.channel} to {self.contact_id} at {self.sent_at}>'


class User(db.Model):
    """Application users. Each user has a username, password hash and a
    role defining their permissions. Roles include:
    - master: can add users, assign roles and edit page permissions.
    - management: full access to all customer data (add/edit/delete contacts).
    - engineer: limited access defined by the master user.
    - billing: limited access defined by the master user.
    """

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    role = db.Column(db.String(50), nullable=False, default='engineer')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f'<User {self.username}>'


# ScheduledEmail model for deferred sending of outbound emails.
class ScheduledEmail(db.Model):
    """Represents an email that should be sent at a future date/time.

    Each record specifies the contact recipient, email subject and body,
    a start timestamp and optional end timestamp for recurring sends, and
    whether the email should recur indefinitely (daily) until the end time.
    """
    id = db.Column(db.Integer, primary_key=True)
    contact_id = db.Column(db.Integer, db.ForeignKey('contact.id'), nullable=False)
    subject = db.Column(db.String(255), nullable=False)
    body = db.Column(db.Text, nullable=False)
    start_at = db.Column(db.DateTime, nullable=False)
    end_at = db.Column(db.DateTime, nullable=True)
    recurring = db.Column(db.Boolean, default=False)
    sent_at = db.Column(db.DateTime, nullable=True)

    def __repr__(self) -> str:
        return f'<ScheduledEmail to={self.contact_id} start={self.start_at} recurring={self.recurring}>'


def schedule_email_job(app: Flask, scheduled: 'ScheduledEmail') -> None:
    """Internal helper to schedule the sending of a ScheduledEmail.

    When called, this function computes the delay until the `start_at` time
    and registers a timer.  At the scheduled time it will send the email
    using `send_email` and optionally reschedule if `recurring` is True
    and the current time has not passed `end_at` (or `end_at` is None).

    Notes
    -----
    This implementation uses `threading.Timer` and runs within the Flask
    process.  It is not durable across process restarts.  For production
    deployments consider using a task queue (Celery, RQ) or cloud scheduler.
    """
    import threading
    from datetime import datetime, timedelta

    def _send_and_reschedule():
        with app.app_context():
            contact = Contact.query.get(scheduled.contact_id)
            if contact:
                success = send_email(contact.email, scheduled.subject, scheduled.body)
                scheduled.sent_at = datetime.utcnow()
                db.session.commit()
            # If recurring, schedule the next day
            if scheduled.recurring:
                next_time = scheduled.start_at + timedelta(days=1)
                if scheduled.end_at is None or next_time <= scheduled.end_at:
                    # Update scheduled.start_at for next run and commit
                    scheduled.start_at = next_time
                    db.session.commit()
                    # Schedule again for next day
                    delay = max((next_time - datetime.utcnow()).total_seconds(), 0)
                    threading.Timer(delay, _send_and_reschedule).start()

    # Calculate delay until first send
    delay = (scheduled.start_at - datetime.utcnow()).total_seconds()
    if delay < 0:
        delay = 0
    threading.Timer(delay, _send_and_reschedule).start()


def generate_contact_summary(contact: Contact) -> str:
    """Generate a plain-text summary file for the given contact.

    The summary is written into the `summaries` directory inside the
    application root.  The filename includes the contact ID and a
    timestamp to avoid collisions.  Returns the path to the generated file.
    """
    from datetime import datetime
    summary_dir = os.path.join(os.path.dirname(__file__), 'summaries')
    os.makedirs(summary_dir, exist_ok=True)
    timestamp = datetime.utcnow().strftime('%Y%m%d%H%M%S')
    filename = f'{contact.id}_{timestamp}.txt'
    path = os.path.join(summary_dir, filename)
    # Compose summary content
    lines = [
        f'Contact ID: {contact.id}',
        f'Name: {contact.first_name} {contact.last_name}',
        f'Email: {contact.email}',
        f'Phone: {contact.phone}',
        f'Company: {contact.company}',
        f'Address: {contact.address}',
        f'Notes: {contact.notes}',
        '',
        'Pipeline:',
        f'  Potential Spend: ${contact.potential_spend:.2f}',
        f'  Accepted Spend: ${contact.accepted_spend:.2f}',
        f'  Billed Amount: ${contact.billed_amount:.2f}',
        f'  Received Amount: ${contact.received_amount:.2f}',
        f'  Rating (1-10): {contact.rating}',
    ]
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(lines))
    return path


def send_email(to_address: str, subject: str, body: str) -> bool:
    """Sends an email using SMTP settings defined via environment variables.

    This helper supports both TLS (typically port 587) and SSL (port 465)
    connections.  By default it attempts to use TLS via `SMTP.starttls()`.
    If the port is 465 or the optional environment variable ``SMTP_USE_SSL``
    is set to a truthy value, the function will instead use ``SMTP_SSL``.

    Parameters
    ----------
    to_address : str
        The recipient's email address.
    subject : str
        The subject line for the email.
    body : str
        The body content of the email.

    Returns
    -------
    bool
        True if the message was sent successfully, False otherwise.

    Notes
    -----
    You must set the following environment variables for this helper to work:
        ``SMTP_SERVER``, ``SMTP_PORT``, ``SMTP_USERNAME``, ``SMTP_PASSWORD``.
    Optionally set ``SMTP_USE_SSL`` to ``true`` to force SSL, or ``SMTP_USE_TLS``
    to ``false`` to disable TLS for non‑SSL connections.
    If the required values are not defined the function will simply print the
    message contents to the console and return ``False``.  This makes it
    possible to test the CRM without sending real emails.
    """
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    smtp_server = os.environ.get('SMTP_SERVER')
    smtp_port = int(os.environ.get('SMTP_PORT', 587))
    smtp_user = os.environ.get('SMTP_USERNAME')
    smtp_password = os.environ.get('SMTP_PASSWORD')

    # Check required settings
    if not smtp_server or not smtp_user or not smtp_password:
        print('Email not sent: missing SMTP configuration')
        print(f'To: {to_address}\nSubject: {subject}\n\n{body}')
        return False

    # Determine connection type
    use_ssl_env = os.environ.get('SMTP_USE_SSL', '').lower()
    use_tls_env = os.environ.get('SMTP_USE_TLS', 'true').lower()

    use_ssl = use_ssl_env in ('1', 'true', 'yes') or smtp_port == 465
    use_tls = use_tls_env not in ('0', 'false', 'no') and not use_ssl

    msg = MIMEMultipart()
    msg['From'] = smtp_user
    msg['To'] = to_address
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))

    try:
        if use_ssl:
            # SMTP over SSL (implicit TLS)
            with smtplib.SMTP_SSL(smtp_server, smtp_port) as server:
                server.login(smtp_user, smtp_password)
                server.send_message(msg)
        else:
            # Plain SMTP with optional STARTTLS
            with smtplib.SMTP(smtp_server, smtp_port) as server:
                if use_tls:
                    server.starttls()
                server.login(smtp_user, smtp_password)
                server.send_message(msg)
        return True
    except Exception as e:
        # Fail gracefully: print error and return False
        print(f'Email sending failed: {e}')
        return False


def send_sms(to_number: str, body: str) -> bool:
    """Sends an SMS using the Twilio service.

    Parameters
    ----------
    to_number : str
        The recipient's phone number (in E.164 format e.g. +1234567890).
    body : str
        The message content.

    Returns
    -------
    bool
        True if the message was sent successfully, False otherwise.

    Notes
    -----
    This helper requires three environment variables:
        TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER
    Without these settings the function will print the SMS content to
    standard output and return False. To fully enable SMS delivery you
    should sign up for Twilio (or a similar SMS provider) and supply
    your credentials as environment variables.
    """
    account_sid = os.environ.get('TWILIO_ACCOUNT_SID')
    auth_token = os.environ.get('TWILIO_AUTH_TOKEN')
    from_number = os.environ.get('TWILIO_PHONE_NUMBER')

    if not account_sid or not auth_token or not from_number:
        print('SMS not sent: missing Twilio configuration')
        print(f'To: {to_number}\n\n{body}')
        return False

    try:
        from twilio.rest import Client  # type: ignore
    except ImportError:
        print('Twilio library not installed. Install via `pip install twilio`')
        return False

    try:
        client = Client(account_sid, auth_token)
        message = client.messages.create(
            body=body,
            from_=from_number,
            to=to_number
        )
        # Optionally inspect message.sid
        return True
    except Exception as e:
        print(f'SMS sending failed: {e}')
        return False


def register_routes(app: Flask) -> None:
    """Registers all of the Flask routes used for the CRM."""

    def login_required(view):
        """Decorator that redirects anonymous users to the login page."""
        @wraps(view)
        def wrapped_view(**kwargs):
            if g.user is None:
                return redirect(url_for('login'))
            return view(**kwargs)
        return wrapped_view

    def role_required(*roles):
        """Decorator ensuring the logged-in user has one of the specified roles."""
        def decorator(view):
            @wraps(view)
            def wrapped_view(**kwargs):
                if g.user is None:
                    return redirect(url_for('login'))
                if g.user.role.lower() not in [r.lower() for r in roles]:
                    flash('You do not have permission to access this page.', 'danger')
                    return redirect(url_for('index'))
                return view(**kwargs)
            return wrapped_view
        return decorator

    @app.route('/')
    def index():
        # Redirect to the contacts page as the primary entry point
        return redirect(url_for('list_contacts'))

    @app.route('/contacts')
    def list_contacts():
        contacts = Contact.query.order_by(Contact.created_at.desc()).all()
        return render_template('contacts.html', contacts=contacts)

    @app.route('/contact/new', methods=['GET', 'POST'])
    @login_required
    @role_required('master', 'management')
    def create_contact():
        if request.method == 'POST':
            first_name = request.form.get('first_name', '').strip()
            last_name = request.form.get('last_name', '').strip()
            email = request.form.get('email', '').strip()
            phone = request.form.get('phone', '').strip()
            company = request.form.get('company', '').strip()
            address = request.form.get('address', '').strip()
            notes = request.form.get('notes', '').strip()

            # Basic validation
            if not first_name or not last_name or not email:
                flash('First name, last name and email are required.', 'danger')
                return render_template('contact_form.html')

            # Check for duplicate email
            existing = Contact.query.filter_by(email=email).first()
            if existing:
                flash('A contact with that email already exists.', 'warning')
                return render_template('contact_form.html')

            # Parse pipeline values
            try:
                potential_spend = float(request.form.get('potential_spend', '0') or 0)
            except ValueError:
                potential_spend = 0.0
            try:
                accepted_spend = float(request.form.get('accepted_spend', '0') or 0)
            except ValueError:
                accepted_spend = 0.0
            try:
                billed_amount = float(request.form.get('billed_amount', '0') or 0)
            except ValueError:
                billed_amount = 0.0
            try:
                received_amount = float(request.form.get('received_amount', '0') or 0)
            except ValueError:
                received_amount = 0.0
            try:
                rating = int(request.form.get('rating', '0') or 0)
            except ValueError:
                rating = 0
            contact = Contact(
                first_name=first_name,
                last_name=last_name,
                email=email,
                phone=phone,
                company=company,
                address=address,
                notes=notes,
                potential_spend=potential_spend,
                accepted_spend=accepted_spend,
                billed_amount=billed_amount,
                received_amount=received_amount,
                rating=rating
            )
            db.session.add(contact)
            db.session.commit()
            # Generate a summary after creation
            generate_contact_summary(contact)
            flash('Contact created successfully!', 'success')
            return redirect(url_for('list_contacts'))
        return render_template('contact_form.html')

    @app.route('/contact/<int:contact_id>')
    def view_contact(contact_id):
        contact = Contact.query.get_or_404(contact_id)
        return render_template('contact_detail.html', contact=contact)

    @app.route('/contact/<int:contact_id>/edit', methods=['GET', 'POST'])
    @login_required
    @role_required('master', 'management')
    def edit_contact(contact_id):
        contact = Contact.query.get_or_404(contact_id)
        if request.method == 'POST':
            contact.first_name = request.form.get('first_name', '').strip()
            contact.last_name = request.form.get('last_name', '').strip()
            contact.email = request.form.get('email', '').strip()
            contact.phone = request.form.get('phone', '').strip()
            contact.company = request.form.get('company', '').strip()
            contact.address = request.form.get('address', '').strip()
            contact.notes = request.form.get('notes', '').strip()
            # Update pipeline values
            try:
                contact.potential_spend = float(request.form.get('potential_spend', contact.potential_spend) or contact.potential_spend)
            except ValueError:
                pass
            try:
                contact.accepted_spend = float(request.form.get('accepted_spend', contact.accepted_spend) or contact.accepted_spend)
            except ValueError:
                pass
            try:
                contact.billed_amount = float(request.form.get('billed_amount', contact.billed_amount) or contact.billed_amount)
            except ValueError:
                pass
            try:
                contact.received_amount = float(request.form.get('received_amount', contact.received_amount) or contact.received_amount)
            except ValueError:
                pass
            try:
                contact.rating = int(request.form.get('rating', contact.rating) or contact.rating)
            except ValueError:
                pass
            db.session.commit()
            # Generate summary after update
            generate_contact_summary(contact)
            flash('Contact updated successfully!', 'success')
            return redirect(url_for('view_contact', contact_id=contact.id))
        return render_template('contact_form.html', contact=contact)

    @app.route('/contact/<int:contact_id>/delete', methods=['POST'])
    @login_required
    @role_required('master', 'management')
    def delete_contact(contact_id):
        contact = Contact.query.get_or_404(contact_id)
        db.session.delete(contact)
        db.session.commit()
        flash('Contact deleted.', 'success')
        return redirect(url_for('list_contacts'))

    @app.route('/message/new/<int:contact_id>', methods=['GET', 'POST'])
    @login_required
    def send_message_route(contact_id):
        contact = Contact.query.get_or_404(contact_id)
        if request.method == 'POST':
            channel = request.form.get('channel')
            subject = request.form.get('subject', '').strip()
            body = request.form.get('body', '').strip()
            # Check if user requested a test email
            is_test = request.form.get('send_test') == '1'
            # Retrieve scheduling fields
            start_at_str = request.form.get('start_at', '')
            end_at_str = request.form.get('end_at', '')
            recurring = request.form.get('recurring', '') == 'on'

            # Basic validation for channel and body
            if channel not in ('email', 'sms') or not body:
                flash('Please choose a valid channel and provide a message body.', 'danger')
                return render_template('message_form.html', contact=contact)

            # Test email: immediately send and do not record schedule
            if is_test:
                if channel == 'email':
                    if not subject:
                        flash('A subject line is required for test emails.', 'danger')
                        return render_template('message_form.html', contact=contact)
                    sent = send_email(contact.email, subject, body)
                else:
                    sent = send_sms(contact.phone or '', body)
                if sent:
                    flash('Test message sent successfully!', 'success')
                else:
                    flash('Test message could not be sent.', 'warning')
                return redirect(url_for('view_contact', contact_id=contact.id))

            # If scheduling an email (channel must be email)
            if start_at_str and channel == 'email':
                from datetime import datetime
                try:
                    start_at = datetime.fromisoformat(start_at_str)
                except ValueError:
                    flash('Invalid start date/time format.', 'danger')
                    return render_template('message_form.html', contact=contact)
                end_at = None
                if end_at_str:
                    try:
                        end_at = datetime.fromisoformat(end_at_str)
                    except ValueError:
                        flash('Invalid end date/time format.', 'danger')
                        return render_template('message_form.html', contact=contact)
                # Create a ScheduledEmail record
                scheduled = ScheduledEmail(
                    contact_id=contact.id,
                    subject=subject or '',
                    body=body,
                    start_at=start_at,
                    end_at=end_at,
                    recurring=recurring
                )
                db.session.add(scheduled)
                db.session.commit()
                # Schedule the job
                schedule_email_job(app, scheduled)
                flash('Email scheduled successfully.', 'success')
                return redirect(url_for('view_contact', contact_id=contact.id))

            # Immediate send
            success = False
            if channel == 'email':
                # Ensure subject provided
                if not subject:
                    flash('A subject line is required when sending an email.', 'danger')
                    return render_template('message_form.html', contact=contact)
                success = send_email(contact.email, subject, body)
            else:
                success = send_sms(contact.phone or '', body)
            if success:
                message = Message(
                    contact_id=contact.id,
                    channel=channel,
                    subject=subject if channel == 'email' else None,
                    body=body
                )
                db.session.add(message)
                db.session.commit()
                flash('Message sent successfully!', 'success')
            else:
                flash('Message could not be sent. Check server logs for details.', 'warning')
            return redirect(url_for('view_contact', contact_id=contact.id))
        return render_template('message_form.html', contact=contact)

    # User authentication routes
    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if request.method == 'POST':
            username = request.form.get('username', '').strip()
            password = request.form.get('password', '').strip()
            user = User.query.filter_by(username=username).first()
            if user and user.check_password(password):
                session.clear()
                session['user_id'] = user.id
                flash('Logged in successfully.', 'success')
                return redirect(url_for('index'))
            flash('Invalid username or password.', 'danger')
        return render_template('login.html')

    @app.route('/logout')
    @login_required
    def logout():
        session.clear()
        flash('You have been logged out.', 'success')
        return redirect(url_for('login'))

    # User management (Master role only)
    @app.route('/users')
    @login_required
    @role_required('master')
    def list_users():
        users = User.query.order_by(User.created_at.desc()).all()
        return render_template('users.html', users=users)

    @app.route('/users/new', methods=['GET', 'POST'])
    @login_required
    @role_required('master')
    def create_user():
        if request.method == 'POST':
            username = request.form.get('username', '').strip()
            password = request.form.get('password', '').strip()
            role = request.form.get('role', 'engineer').strip().lower()
            if not username or not password:
                flash('Username and password are required.', 'danger')
                return render_template('user_form.html')
            if User.query.filter_by(username=username).first():
                flash('A user with that username already exists.', 'warning')
                return render_template('user_form.html')
            if role not in ('master', 'management', 'engineer', 'billing'):
                flash('Invalid role selected.', 'danger')
                return render_template('user_form.html')
            new_user = User(username=username, role=role)
            new_user.set_password(password)
            db.session.add(new_user)
            db.session.commit()
            flash('User created successfully.', 'success')
            return redirect(url_for('list_users'))
        return render_template('user_form.html')

    # Generate summary on demand for a contact
    @app.route('/contact/<int:contact_id>/summary', methods=['POST'])
    @login_required
    @role_required('master', 'management')
    def generate_summary(contact_id):
        contact = Contact.query.get_or_404(contact_id)
        path = generate_contact_summary(contact)
        flash(f'Summary generated at {path}', 'success')
        return redirect(url_for('view_contact', contact_id=contact.id))
