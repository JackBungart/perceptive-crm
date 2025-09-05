#!/usr/bin/env python3
"""
Lightweight CRM email scheduler using only Python standard libraries.

This script implements a tiny HTTP server that allows you to:

 * View a list of contacts
 * Schedule recurring emails (daily, weekly, monthly, yearly, or custom intervals)
 * View and delete existing schedules

It stores contacts and schedules in a local SQLite database, runs a
background scheduler thread to dispatch emails at the appropriate
times, and uses smtplib to send messages.  Designed for environments
where external packages like Flask cannot be installed.  Integrate or
adapt this into your existing system by replacing the contact and
schedule persistence layers and server implementation as needed.
"""
import sqlite3
import threading
import time
from datetime import datetime, timedelta
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import smtplib
import ssl


DB_PATH = 'crm_scheduler.db'
SERVER_PORT = 8000


def init_db():
    """Create tables and insert sample contacts if necessary."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # contacts table
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            phone TEXT,
            company TEXT
        )
        """
    )
    # schedules table
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS schedules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            contact_id INTEGER NOT NULL,
            subject TEXT NOT NULL,
            body TEXT NOT NULL,
            trigger_type TEXT NOT NULL,
            hour INTEGER,
            minute INTEGER,
            day_of_week TEXT,
            day TEXT,
            month TEXT,
            interval_seconds INTEGER,
            next_run_time REAL,
            last_run_time REAL,
            FOREIGN KEY(contact_id) REFERENCES contacts(id)
        )
        """
    )
    # Prepopulate contacts if empty
    c.execute("SELECT COUNT(*) FROM contacts")
    count = c.fetchone()[0]
    if count == 0:
        sample_contacts = [
            ('larry west', 'lwest@perceptivecontrol.com', 'test', 'perceptive'),
            ('jack is', 'JBUNGART@PERCEPTIVECONTROLS.COM', 'the man', 'perceptivecontrols'),
        ]
        c.executemany("INSERT INTO contacts (name, email, phone, company) VALUES (?, ?, ?, ?)", sample_contacts)
    conn.commit()
    conn.close()


def send_email(to_address: str, subject: str, body: str):
    """
    Send an email via SMTP.  Uses TLS by default.  Modify the
    configuration below to suit your environment.
    """
    server_config = {
        'host': 'gator4334.hostgator.com',
        'port': 587,
        'username': 'PerceptiveCRM@optoalarms.com',
        'password': 'PerceptiveCRM!@1',
        'use_ssl': False,
    }
    msg = MIMEMultipart()
    msg['From'] = server_config['username']
    msg['To'] = to_address
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))
    if server_config['use_ssl']:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(server_config['host'], server_config['port'], context=context) as server:
            server.login(server_config['username'], server_config['password'])
            server.send_message(msg)
    else:
        with smtplib.SMTP(server_config['host'], server_config['port']) as server:
            server.ehlo()
            server.starttls()
            server.login(server_config['username'], server_config['password'])
            server.send_message(msg)


class Scheduler(threading.Thread):
    """
    Background thread that polls the database for due schedules and
    sends emails when it's time.  It recalculates the next_run_time
    based on the trigger configuration after each run.
    """
    def __init__(self, db_path: str):
        super().__init__(daemon=True)
        self.db_path = db_path
        self.stop_event = threading.Event()

    def run(self):
        while not self.stop_event.is_set():
            try:
                self.tick()
            except Exception as exc:
                # Print the exception; in production, log properly
                print(f"Scheduler error: {exc}")
            # Sleep for 60 seconds between iterations
            self.stop_event.wait(60)

    def tick(self):
        now_ts = time.time()
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        # Fetch schedules that are due
        c.execute(
            "SELECT s.id, s.contact_id, s.subject, s.body, s.trigger_type, "
            "s.hour, s.minute, s.day_of_week, s.day, s.month, s.interval_seconds, s.next_run_time, s.last_run_time, c.email "
            "FROM schedules s JOIN contacts c ON s.contact_id = c.id "
            "WHERE s.next_run_time IS NOT NULL AND s.next_run_time <= ?",
            (now_ts,)
        )
        due_schedules = c.fetchall()
        for row in due_schedules:
            (sid, contact_id, subject, body, trigger_type, hour, minute,
             day_of_week, day, month, interval_seconds, next_run_time,
             last_run_time, email) = row
            # Send the email
            try:
                send_email(email, subject, body)
                print(f"Sent scheduled email {sid} to {email} at {datetime.utcnow()} UTC")
            except Exception as exc:
                print(f"Failed to send email for schedule {sid}: {exc}")
            # Update last_run_time and compute next_run_time
            last_run_dt = datetime.utcnow()
            next_run_dt = compute_next_run(
                trigger_type=trigger_type,
                hour=hour,
                minute=minute,
                day_of_week=day_of_week,
                day=day,
                month=month,
                interval_seconds=interval_seconds,
                from_time=last_run_dt,
            )
            next_run_ts = next_run_dt.timestamp() if next_run_dt else None
            c.execute(
                "UPDATE schedules SET last_run_time = ?, next_run_time = ? WHERE id = ?",
                (last_run_dt.timestamp(), next_run_ts, sid),
            )
        conn.commit()
        conn.close()

    def stop(self):
        self.stop_event.set()


def compute_next_run(trigger_type, hour, minute, day_of_week, day, month, interval_seconds, from_time):
    """
    Compute the next run datetime for a schedule given its trigger
    configuration.  `from_time` is the baseline time from which to
    calculate the next occurrence (typically the time the job last
    executed).
    Returns a datetime or None if no further runs should be scheduled.
    """
    # Normalize hour/minute
    hour = hour if hour is not None else 0
    minute = minute if minute is not None else 0
    if trigger_type == 'custom':
        if not interval_seconds:
            return None
        return from_time + timedelta(seconds=interval_seconds)
    # For calendar-based triggers, we search for the next valid time.
    next_time = from_time.replace(second=0, microsecond=0) + timedelta(minutes=1)
    for _ in range(365 * 5):  # search up to 5 years ahead
        if trigger_type == 'daily':
            candidate = next_time.replace(hour=hour, minute=minute)
            if candidate < next_time:
                candidate += timedelta(days=1)
            return candidate
        elif trigger_type == 'weekly':
            # day_of_week can be comma-separated list or '*' for every day
            days = list(range(7)) if not day_of_week or day_of_week == '*' else [int(d) for d in day_of_week.split(',')]
            candidate = next_time.replace(hour=hour, minute=minute)
            # If candidate not on allowed day or in past, move forward one day until matched
            while candidate.weekday() not in days or candidate < next_time:
                candidate += timedelta(days=1)
            return candidate
        elif trigger_type == 'monthly':
            # day may be '*' or comma-separated days
            days = list(range(1, 32)) if not day or day == '*' else [int(d) for d in day.split(',')]
            candidate = next_time.replace(hour=hour, minute=minute)
            # If candidate not on allowed day or in past, move forward one day
            while (candidate.day not in days or candidate < next_time):
                candidate += timedelta(days=1)
                candidate = candidate.replace(hour=hour, minute=minute)
            return candidate
        elif trigger_type == 'yearly':
            # month and day may be '*' or numeric
            months = list(range(1, 13)) if not month or month == '*' else [int(m) for m in month.split(',')]
            days = list(range(1, 32)) if not day or day == '*' else [int(d) for d in day.split(',')]
            candidate = next_time.replace(hour=hour, minute=minute)
            # Move forward one day until month/day matches
            while ((candidate.month not in months) or (candidate.day not in days) or candidate < next_time):
                candidate += timedelta(days=1)
                candidate = candidate.replace(hour=hour, minute=minute)
            return candidate
        else:
            return None
    return None


class CRMRequestHandler(BaseHTTPRequestHandler):
    """
    HTTP request handler implementing a few routes for the CRM.

    Supported paths:
    - /contacts: display list of contacts
    - /schedule_email (GET): display the scheduling form
    - /schedule_email (POST): process form submission and create schedule
    - /email_schedules: list all schedules
    - /delete_schedule?id=N: delete schedule with id N (POST)
    """

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path == '/' or path == '/contacts':
            self.render_contacts()
        elif path == '/schedule_email':
            self.render_schedule_form()
        elif path == '/email_schedules':
            self.render_schedules()
        else:
            self.send_error(404, 'Not Found')

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path == '/schedule_email':
            self.handle_schedule_form()
        elif path == '/delete_schedule':
            self.handle_delete_schedule()
        else:
            self.send_error(404, 'Not Found')

    # Helpers to access database
    def get_contacts(self):
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT id, name, email, phone, company FROM contacts")
        contacts = c.fetchall()
        conn.close()
        return contacts

    def get_schedules(self):
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            "SELECT s.id, c.name, c.email, s.subject, s.trigger_type, s.next_run_time "
            "FROM schedules s JOIN contacts c ON s.contact_id = c.id"
        )
        rows = c.fetchall()
        conn.close()
        return rows

    # HTML pages
    def render_contacts(self):
        contacts = self.get_contacts()
        body = """
        <h1>Contacts</h1>
        <a class="btn" href="/schedule_email">Schedule Email</a>
        <table>
          <thead><tr><th>Name</th><th>Email</th><th>Phone</th><th>Company</th></tr></thead>
          <tbody>
        """
        for cid, name, email, phone, company in contacts:
            body += f"<tr><td>{name}</td><td>{email}</td><td>{phone or ''}</td><td>{company or ''}</td></tr>"
        body += """
          </tbody>
        </table>
        """
        html = self.render_base('Contacts', body)
        self.respond_html(html)

    def render_schedules(self):
        schedules = self.get_schedules()
        body = """
        <h1>Scheduled Emails</h1>
        <a class="btn" href="/schedule_email">New Schedule</a>
        <table>
          <thead><tr><th>Contact</th><th>Email</th><th>Subject</th><th>Frequency</th><th>Next Run (UTC)</th><th>Actions</th></tr></thead>
          <tbody>
        """
        for sid, name, email, subject, trigger_type, next_run_time in schedules:
            next_run_str = datetime.utcfromtimestamp(next_run_time).strftime('%Y-%m-%d %H:%M') if next_run_time else 'Pending'
            body += f"<tr><td>{name}</td><td>{email}</td><td>{subject}</td><td>{trigger_type}</td><td>{next_run_str}</td>"
            body += f"<td><form method='post' action='/delete_schedule'><input type='hidden' name='id' value='{sid}'/>"
            body += f"<button type='submit'>Delete</button></form></td></tr>"
        body += """
          </tbody>
        </table>
        """
        html = self.render_base('Scheduled Emails', body)
        self.respond_html(html)

    def render_schedule_form(self):
        contacts = self.get_contacts()
        # Build options for contacts select
        options = ''.join([f"<option value='{cid}'>{name} ({email})</option>" for cid, name, email, _, _ in contacts])
        body = f"""
        <h1>Schedule Email</h1>
        <form method='post' action='/schedule_email'>
          <label>Contact:</label>
          <select name='contact_id' required>{options}</select><br/>
          <label>Subject:</label>
          <input type='text' name='subject' required/><br/>
          <label>Body:</label>
          <textarea name='body' rows='4' cols='40' required></textarea><br/>
          <label>Frequency:</label>
          <select name='frequency' id='frequency' onchange='updateFields()'>
            <option value='daily'>Daily</option>
            <option value='weekly'>Weekly</option>
            <option value='monthly'>Monthly</option>
            <option value='yearly'>Yearly</option>
            <option value='custom'>Custom (interval)</option>
          </select><br/>
          <div id='cron-fields'>
            <label>Hour (0-23):</label><input type='number' name='hour' min='0' max='23' value='9'/><br/>
            <label>Minute (0-59):</label><input type='number' name='minute' min='0' max='59' value='0'/><br/>
            <div id='weekly-field' style='display:none;'>
              <label>Day of Week (0=Mon .. 6=Sun or *, comma sep):</label><input type='text' name='day_of_week' placeholder='*'/><br/>
            </div>
            <div id='monthly-field' style='display:none;'>
              <label>Day of Month (1-31 or *, comma sep):</label><input type='text' name='day' placeholder='*'/><br/>
            </div>
            <div id='yearly-field' style='display:none;'>
              <label>Month (1-12 or *, comma sep):</label><input type='text' name='month' placeholder='*'/><br/>
              <label>Day of Month (1-31 or *, comma sep):</label><input type='text' name='day_in_year' placeholder='*'/><br/>
            </div>
          </div>
          <div id='custom-field' style='display:none;'>
            <label>Interval (minutes):</label><input type='number' name='interval_minutes' min='1' value='60'/><br/>
          </div>
          <button type='submit'>Create</button>
        </form>
        <script>
        function updateFields() {{
          var freq = document.getElementById('frequency').value;
          document.getElementById('cron-fields').style.display = (freq === 'custom') ? 'none' : 'block';
          document.getElementById('custom-field').style.display = (freq === 'custom') ? 'block' : 'none';
          document.getElementById('weekly-field').style.display = (freq === 'weekly') ? 'block' : 'none';
          var monthlyVisible = (freq === 'monthly' || freq === 'yearly');
          document.getElementById('monthly-field').style.display = monthlyVisible ? 'block' : 'none';
          document.getElementById('yearly-field').style.display = (freq === 'yearly') ? 'block' : 'none';
        }}
        document.addEventListener('DOMContentLoaded', updateFields);
        </script>
        """
        html = self.render_base('Schedule Email', body)
        self.respond_html(html)

    def handle_schedule_form(self):
        # Parse form data
        length = int(self.headers.get('Content-Length', 0))
        data = self.rfile.read(length).decode('utf-8')
        params = urllib.parse.parse_qs(data)
        # Extract values
        contact_id = int(params.get('contact_id', [''])[0])
        subject = params.get('subject', [''])[0]
        body = params.get('body', [''])[0]
        frequency = params.get('frequency', [''])[0]
        hour = params.get('hour', [None])[0]
        minute = params.get('minute', [None])[0]
        day_of_week = params.get('day_of_week', [''])[0]
        day = params.get('day', [''])[0]
        # day_in_year overrides day for yearly schedules
        day_in_year = params.get('day_in_year', [''])[0]
        month = params.get('month', [''])[0]
        interval_minutes = params.get('interval_minutes', [''])[0]
        # Convert numeric values
        hour_val = int(hour) if hour not in (None, '', 'None') else None
        minute_val = int(minute) if minute not in (None, '', 'None') else None
        day_of_week_val = day_of_week if day_of_week else None
        # Choose correct day value
        day_val = None
        if frequency == 'yearly':
            day_val = day_in_year if day_in_year else None
        else:
            day_val = day if day else None
        month_val = month if month else None
        interval_seconds = None
        if frequency == 'custom':
            try:
                interval_seconds = int(interval_minutes) * 60 if interval_minutes else None
            except ValueError:
                interval_seconds = None
        # Compute first run time
        now = datetime.utcnow()
        next_run_dt = compute_next_run(
            trigger_type=frequency,
            hour=hour_val,
            minute=minute_val,
            day_of_week=day_of_week_val,
            day=day_val,
            month=month_val,
            interval_seconds=interval_seconds,
            from_time=now - timedelta(minutes=1)
        )
        next_run_ts = next_run_dt.timestamp() if next_run_dt else None
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            "INSERT INTO schedules (contact_id, subject, body, trigger_type, hour, minute, day_of_week, day, month, interval_seconds, next_run_time) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (contact_id, subject, body, frequency, hour_val, minute_val, day_of_week_val, day_val, month_val, interval_seconds, next_run_ts)
        )
        conn.commit()
        conn.close()
        # Redirect back to schedules list
        self.send_response(303)
        self.send_header('Location', '/email_schedules')
        self.end_headers()

    def handle_delete_schedule(self):
        length = int(self.headers.get('Content-Length', 0))
        data = self.rfile.read(length).decode('utf-8')
        params = urllib.parse.parse_qs(data)
        sid = int(params.get('id', [''])[0])
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("DELETE FROM schedules WHERE id = ?", (sid,))
        conn.commit()
        conn.close()
        # Redirect back to schedules list
        self.send_response(303)
        self.send_header('Location', '/email_schedules')
        self.end_headers()

    def render_base(self, title: str, body: str) -> str:
        """Wrap body HTML in a simple page layout."""
        # Minimal CSS for readability
        return f"""<!DOCTYPE html>
        <html lang='en'>
        <head>
          <meta charset='utf-8'>
          <title>{title}</title>
          <style>
            body {{ background-color: #1e1e1e; color: #ddd; font-family: Arial, sans-serif; padding: 20px; }}
            table {{ border-collapse: collapse; width: 100%; margin-top: 1em; }}
            th, td {{ border: 1px solid #444; padding: 8px; text-align: left; }}
            th {{ background-color: #333; }}
            tr:nth-child(even) {{ background-color: #2b2b2b; }}
            a.btn, button {{ background-color: #007bff; color: white; padding: 6px 12px; text-decoration: none; border: none; border-radius: 4px; cursor: pointer; }}
            a.btn {{ margin-right: 5px; }}
            button {{ margin: 0; }}
            form {{ margin-top: 1em; }}
            label {{ display: block; margin-top: 0.5em; }}
            input[type='text'], input[type='number'], textarea, select {{ width: 100%; max-width: 400px; padding: 4px; margin-top: 0.2em; background-color: #2b2b2b; color: #ddd; border: 1px solid #555; border-radius: 4px; }}
          </style>
        </head>
        <body>
          <nav>
            <a class='btn' href='/contacts'>Contacts</a>
            <a class='btn' href='/schedule_email'>Schedule Email</a>
            <a class='btn' href='/email_schedules'>Scheduled Jobs</a>
          </nav>
          {body}
        </body>
        </html>"""

    def respond_html(self, html: str):
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(html.encode('utf-8'))


def run_server():
    init_db()
    scheduler = Scheduler(DB_PATH)
    scheduler.start()
    server_address = ('', SERVER_PORT)
    httpd = HTTPServer(server_address, CRMRequestHandler)
    print(f"Server running at http://localhost:{SERVER_PORT}/contacts")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        scheduler.stop()
        httpd.server_close()


if __name__ == '__main__':
    run_server()
