# Maintenance and Update Routines

This document outlines the regular tasks required to keep the internal CRM system running smoothly and securely.  It also describes how to update the codebase and database as new features are added.

## Routine Maintenance

1. **Daily Backups**
   - Schedule an automated backup of the SQLite or PostgreSQL database every night.  For SQLite, copy the `.db` file to an off‑site location.  For PostgreSQL, use `pg_dump` or a managed backup service.
   - Verify backup integrity weekly by restoring the backup into a test environment.

2. **Log Monitoring**
   - Configure logging for Flask (e.g., via `logging` and `RotatingFileHandler`).  Review logs daily for errors such as failed emails, authentication issues, or database errors.
   - Set up alerts for critical errors (e.g., email sending failures) using a tool like Prometheus + Grafana or a simpler cron script.

3. **Security Patches**
   - Every month, review dependency updates (`pip list --outdated`) and apply patches for Flask, SQLAlchemy, and other libraries.  Use a staging environment to test updates before deploying to production.
   - Rotate secrets (SMTP passwords, Twilio tokens, secret keys) at least quarterly.  Store secrets using environment variables or a secrets manager.

4. **User Management**
   - Periodically review active user accounts.  Remove or disable accounts for former employees.  Verify that roles align with job functions.
   - Require strong passwords and consider two‑factor authentication on the hosting platform and email provider.

5. **Data Hygiene**
   - Encourage staff to keep contact information accurate.  Use the rating field to prioritise follow‑up and purge or archive stale leads annually.
   - Run a quarterly audit of financial pipeline fields (potential, accepted, billed, received) to ensure they reconcile with actual invoices and payments in the accounting system.

## Update Process

1. **Version Control and Branching**
   - Maintain all code in a Git repository (`perceptive‑crm`).  Use feature branches for new functionality (e.g., `feature/email-scheduler`).  Merge into `main` after code review and testing.
   - Tag releases (e.g., `v1.0.0`, `v1.1.0`) and generate release notes summarising changes.

2. **Local Development Environment**
   - Developers should set up a Python virtual environment (`python -m venv venv`) and install dependencies with `pip install -r requirements.txt`.
   - Use a separate SQLite database for development.  Do not work directly on production data.

3. **Database Migrations**
   - When adding or altering models (e.g., adding new pipeline fields), use a migration tool such as Flask‑Migrate (Alembic) rather than manually editing the database.  Generate migration scripts (`flask db migrate`) and apply them in development before running in production (`flask db upgrade`).

4. **Testing**
   - Implement unit and integration tests using `pytest` or Flask’s built‑in testing utilities.  Tests should cover routes, authentication, scheduled emails, and summary generation.
   - Execute the test suite (`pytest`) before each deployment.  Consider automating tests via GitHub Actions or another CI system.

5. **Deployment Routine**
   - Deploy updates during low‑traffic hours.  Use `git pull` on the server to fetch new changes.  Restart the application (e.g., `systemctl restart crm.service` or restart Gunicorn) and verify that the website loads without errors.
   - After deployment, run database migrations if applicable.  Monitor logs for any migration errors.

6. **Documentation**
   - Keep documentation (e.g., this file and user instructions) in the repository up to date.  Update the README with new environment variables or dependencies.
   - Provide a change log summarising enhancements and bug fixes in each version.

## Path to Success

1. **Start Small and Iterate**: Begin with core functionality (contacts, messages, scheduling).  Gather feedback from users and prioritise enhancements.
2. **Automate Early**: Integrate continuous integration/continuous deployment (CI/CD) pipelines to run tests and deploy automatically after approvals.
3. **Prioritise User Experience**: Ensure the interface is intuitive.  Provide tooltips and default values.  Regularly interview users to understand pain points.
4. **Plan for Scale**: If the number of contacts grows significantly, consider migrating from SQLite to PostgreSQL and from simple timers to a robust task queue (Celery + Redis) for scheduling emails.
5. **Stay Compliant**: Follow data privacy regulations (e.g., GDPR, HIPAA) if applicable.  Implement role‑based access control (already in place) and audit trails of data changes.
6. **Regularly Review and Refactor**: Schedule quarterly code reviews.  Refactor as needed to reduce complexity and technical debt.
