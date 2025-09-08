# Import the factory and database from the local package.  When run via
# `python run.py` this file sits alongside `app.py` so we import
# directly from `app` rather than using the package name.
from app import create_app, db

app = create_app()

if __name__ == '__main__':
    # Create all database tables if they do not exist
    with app.app_context():
        db.create_all()
    # Use a non-reserved port (e.g., 5500) to avoid Windows socket restrictions.
    # Adjust this value if the port is in use or you prefer another port.
    app.run(host='0.0.0.0', port=5500, debug=True)