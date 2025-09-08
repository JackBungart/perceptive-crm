# Internal CRM Implementation Timeline

This timeline assumes a small team of 1–2 developers familiar with Flask and SQLAlchemy.  It is designed for Perceptive Controls’ current scope (contact management, email/SMS communication, financial pipeline tracking, user roles, and summary generation).  Durations are estimates; actual times may vary with complexity and feedback cycles.

| Phase                     | Duration    | Activities |
|---------------------------|------------:|-----------|
| **Planning & Requirements** | 1 week     | Gather detailed requirements from sales, engineering, billing.  Document desired fields (potential/accepted spend, billed/received amounts, ratings), email scheduling rules, user roles and permissions.  Decide hosting environment and domain configuration (e.g., subdomain on `PerceptiveControls.com`). |
| **Design**                | 1 week      | Define database schema (Contact, User, Message, ScheduledEmail).  Sketch UI wireframes.  Plan API endpoints for integrations.  Decide technology stack (Flask + SQLAlchemy + Bootstrap + Twilio + SMTP). |
| **Initial Development**   | 2 weeks     | Implement core CRUD for contacts and users.  Add authentication and role‑based access control.  Build email/SMS sending with test option.  Create pipeline fields and forms.  Implement automatic summary generation on data changes. |
| **Scheduling & Automation** | 1 week      | Add scheduling model and background task (e.g., using APScheduler or simple timers) to send emails at future times.  Implement recurring daily sends with optional end date.  Build manual summary trigger. |
| **Testing & Bug Fixing**  | 1–2 weeks   | Conduct manual and unit testing across all roles.  Validate email and SMS delivery.  Ensure financial fields update correctly.  Fix edge cases (invalid dates, missing data). |
| **Deployment Setup**      | 1 week      | Prepare server (Ubuntu or Windows Server) with Python 3, virtual environment, and web server (Gunicorn + Nginx or IIS).  Configure environment variables for SMTP/Twilio.  Set up HTTPS using Let’s Encrypt.  Deploy the app and perform smoke testing. |
| **Training & Rollout**    | 1 week      | Train sales, management, engineering and billing teams.  Provide documentation on logging in, adding contacts, scheduling emails, and generating summaries.  Collect feedback for improvements. |
| **Total**                 | **7–8 weeks** | |

### Notes

* **Parallel Work:** Some phases can overlap.  While development begins, design refinements and hosting preparations can occur in parallel.
* **Future Enhancements:** After initial rollout, plan a phase for deeper analytics, reporting dashboards, and integration with quoting/billing systems.  This could extend the timeline by 2–3 weeks.
* **Contingencies:** Allow additional buffer time (1–2 weeks) for unforeseen obstacles, such as third‑party API limits, authentication setup, or change requests.
