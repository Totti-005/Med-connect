# MedConnect

A patient medication tracking app built with Flask, MySQL, and server-rendered HTML/CSS/JavaScript.

## Run locally

1. Create a virtual environment: `python -m venv .venv`
2. Activate it in PowerShell: `.venv\Scripts\Activate.ps1`
3. Install dependencies: `pip install -r requirements.txt`
4. Copy `.env.example` to `.env` and set `SECRET_KEY`. Set `ADMIN_EMAIL` to the email that should have the admin role. For WAMP, use `DATABASE_URL=mysql+pymysql://root:@127.0.0.1:3306/medconnect` unless you configured a MySQL password or different port.
5. Start the app: `python app.py`
6. Open `http://localhost:5000`

## Windows launcher

Double-click `start_medconnect_server.bat` from the project folder. It opens `http://localhost:5000` in the browser, starts the existing `python app.py` server command, and keeps the terminal open after the server stops so logs and errors remain visible. Ensure WAMP MySQL is running before launching.

## WAMP / MySQL

Start the MySQL service in the WAMP control panel, open phpMyAdmin, and run `schema.sql` to create the `medconnect` database. The default WAMP connection is `mysql+pymysql://root:@127.0.0.1:3306/medconnect`; update the username, password, or port in `.env` if your WAMP installation differs. Flask-SQLAlchemy creates the tables on first startup.


## Included

- Patient and caregiver registration and login with hashed passwords
- Admin approval required before caregiver login
- Caregiver medication assignment directly to a patient dashboard
- Caregiver medicine autocomplete powered by the RxNorm catalog, with offline common-medicine fallback
- Medication schedule creation with multiple daily times
- Dashboard with adherence summary and dose actions
- Browser notification permission and reminder polling
- Medication history and medication removal
- Responsive UI suitable for Render or another Python host

For production, use a strong `SECRET_KEY`, disable `FLASK_DEBUG`, configure HTTPS, and add CSRF protection before exposing forms publicly.
