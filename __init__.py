"""Top-level package for the internal CRM application.

This file allows Python to treat the `crm_app` directory as a package so
that modules like `app` can be imported using the dotted notation
(`crm_app.app`).
"""

from .app import create_app, db, Contact, Message  # noqa: F401