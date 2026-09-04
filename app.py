import os
import json
from datetime import date, datetime
from functools import wraps
from urllib.parse import quote
from urllib.request import urlopen

from flask import Flask, flash, redirect, render_template, request, url_for
from flask_login import LoginManager, UserMixin, current_user, login_required, login_user, logout_user
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv
from werkzeug.security import check_password_hash, generate_password_hash

load_dotenv(override=True)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY') or os.urandom(32)
database_url = os.getenv('DATABASE_URL', 'sqlite:///medconnect.db')
if database_url.startswith('mysql://'):
    database_url = database_url.replace('mysql://', 'mysql+pymysql://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
admin_email = os.getenv('ADMIN_EMAIL', '').strip().lower()
admin_password = os.getenv('ADMIN_PASSWORD', '')

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Please sign in to continue.'


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(190), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    phone = db.Column(db.String(40))
    role = db.Column(db.String(20), nullable=False, default='patient')
    approved = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    medications = db.relationship(
        'Medication',
        foreign_keys='Medication.patient_id',
        backref='patient',
        lazy=True,
        cascade='all, delete-orphan',
    )


class Medication(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    prescribed_by_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    medicine_name = db.Column(db.String(120), nullable=False)
    dosage = db.Column(db.String(80), nullable=False)
    frequency = db.Column(db.String(80), nullable=False)
    times = db.Column(db.String(255), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date)
    instructions = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    prescriber = db.relationship('User', foreign_keys=[prescribed_by_id])
    logs = db.relationship('MedicationLog', backref='medication', lazy=True, cascade='all, delete-orphan')


class MedicationLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    medication_id = db.Column(db.Integer, db.ForeignKey('medication.id'), nullable=False)
    scheduled_date = db.Column(db.Date, nullable=False)
    scheduled_time = db.Column(db.String(20), nullable=False)
    status = db.Column(db.String(20), nullable=False)
    taken_at = db.Column(db.DateTime)


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


def parse_times(value):
    return [item.strip() for item in value.split(',') if item.strip()]


def parse_medication_form(form):
    start_date = datetime.strptime(form['start_date'], '%Y-%m-%d').date()
    end_value = form.get('end_date', '').strip()
    end_date = datetime.strptime(end_value, '%Y-%m-%d').date() if end_value else None
    times = parse_times(form.get('times', ''))
    required_fields = ('medicine_name', 'dosage', 'frequency')
    values = {field: form.get(field, '').strip() for field in required_fields}
    if not all(values.values()) or not times or (end_date and end_date < start_date):
        raise ValueError
    return {
        **values,
        'times': ', '.join(times),
        'start_date': start_date,
        'end_date': end_date,
        'instructions': form.get('instructions', '').strip(),
    }


def medication_is_active(medication, on_date):
    return medication.start_date <= on_date and (not medication.end_date or on_date <= medication.end_date)


def dose_status(medication, scheduled_date, scheduled_time):
    log = MedicationLog.query.filter_by(
        medication_id=medication.id,
        scheduled_date=scheduled_date,
        scheduled_time=scheduled_time,
    ).first()
    return log.status if log else 'upcoming'


def dashboard_doses(on_date):
    doses = []
    for medication in current_user.medications:
        if medication_is_active(medication, on_date):
            for scheduled_time in parse_times(medication.times):
                doses.append({
                    'medication': medication,
                    'time': scheduled_time,
                    'status': dose_status(medication, on_date, scheduled_time),
                })
    return sorted(doses, key=lambda dose: dose['time'])


def login_required_page(view):
    return login_required(view)


def role_required(*roles):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if current_user.role not in roles:
                flash('You do not have access to that page.', 'error')
                return redirect(url_for('dashboard'))
            return view(*args, **kwargs)
        return wrapped
    return decorator


def approved_caregiver_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if current_user.role != 'caregiver':
            flash('Only caregivers can assign medication.', 'error')
            return redirect(url_for('dashboard'))
        if not current_user.approved:
            logout_user()
            flash('Your caregiver account is waiting for admin approval.', 'error')
            return redirect(url_for('login'))
        return view(*args, **kwargs)
    return wrapped


@app.context_processor
def inject_helpers():
    return {'today': date.today(), 'parse_times': parse_times, 'format_date': lambda value, pattern='%b %d, %Y': value.strftime(pattern).replace(' 0', ' ')}


@app.route('/')
def index():
    return redirect(url_for('dashboard')) if current_user.is_authenticated else redirect(url_for('login'))


@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip().lower()
        phone = request.form.get('phone', '').strip()
        role = request.form.get('role', 'patient').strip().lower()
        password = request.form.get('password', '')
        if role not in {'patient', 'caregiver'}:
            role = 'patient'
        if not name or not email or len(password) < 8:
            flash('Add your name, a valid email, and a password of at least 8 characters.', 'error')
        elif User.query.filter_by(email=email).first():
            flash('An account with that email already exists.', 'error')
        else:
            is_admin = bool(admin_email and email == admin_email)
            user = User(
                name=name,
                email=email,
                phone=phone,
                role='admin' if is_admin else role,
                approved=True if is_admin else role == 'patient',
                password_hash=generate_password_hash(password),
            )
            db.session.add(user)
            db.session.commit()
            if user.role == 'caregiver':
                flash('Registration received. An admin must approve your caregiver account before you can sign in.', 'success')
                return redirect(url_for('login'))
            login_user(user)
            return redirect(url_for('dashboard'))
    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password_hash, password):
            if user.role == 'caregiver' and not user.approved:
                flash('Your caregiver account is waiting for admin approval.', 'error')
                return render_template('login.html')
            login_user(user)
            return redirect(url_for('dashboard'))
        flash('Email or password is incorrect.', 'error')
    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


@app.route('/dashboard')
@login_required_page
def dashboard():
    if current_user.role == 'admin':
        return redirect(url_for('admin_dashboard'))
    if current_user.role == 'caregiver':
        return redirect(url_for('caregiver_dashboard'))
    doses = dashboard_doses(date.today())
    total = len(doses)
    taken = sum(dose['status'] == 'taken' for dose in doses)
    missed = sum(dose['status'] == 'missed' for dose in doses)
    upcoming = sum(dose['status'] == 'upcoming' for dose in doses)
    adherence = round((taken / (taken + missed)) * 100) if taken + missed else 0
    return render_template('dashboard.html', doses=doses, total=total, taken=taken, missed=missed, upcoming=upcoming, adherence=adherence)


@app.route('/medications', methods=['GET', 'POST'])
@login_required
def medications():
    if current_user.role == 'caregiver':
        return redirect(url_for('caregiver_dashboard'))
    if current_user.role == 'admin':
        return redirect(url_for('admin_dashboard'))
    if request.method == 'POST':
        try:
            medication = Medication(patient_id=current_user.id, **parse_medication_form(request.form))
            db.session.add(medication)
            db.session.commit()
            flash('Medication added to your schedule.', 'success')
            return redirect(url_for('medications'))
        except (KeyError, ValueError):
            db.session.rollback()
            flash('Please complete the required medication details.', 'error')
    user_medications = Medication.query.filter_by(patient_id=current_user.id).order_by(Medication.start_date.desc()).all()
    return render_template('medications.html', medications=user_medications)


@app.route('/medications/<int:medication_id>/delete', methods=['POST'])
@login_required
def delete_medication(medication_id):
    medication = Medication.query.filter_by(id=medication_id, patient_id=current_user.id).first_or_404()
    db.session.delete(medication)
    db.session.commit()
    flash('Medication removed.', 'success')
    return redirect(url_for('medications'))


@app.route('/dose/<int:medication_id>', methods=['POST'])
@login_required
def update_dose(medication_id):
    medication = Medication.query.filter_by(id=medication_id, patient_id=current_user.id).first_or_404()
    status = request.form.get('status')
    scheduled_time = request.form.get('scheduled_time', '').strip()
    if status not in {'taken', 'skipped', 'missed'} or scheduled_time not in parse_times(medication.times):
        flash('That dose update is not valid.', 'error')
        return redirect(url_for('dashboard'))
    log = MedicationLog.query.filter_by(medication_id=medication.id, scheduled_date=date.today(), scheduled_time=scheduled_time).first()
    if not log:
        log = MedicationLog(medication_id=medication.id, scheduled_date=date.today(), scheduled_time=scheduled_time)
        db.session.add(log)
    log.status = status
    log.taken_at = datetime.utcnow() if status == 'taken' else None
    db.session.commit()
    return redirect(url_for('dashboard'))


@app.route('/history')
@login_required
def history():
    logs = MedicationLog.query.join(Medication).filter(Medication.patient_id == current_user.id).order_by(MedicationLog.scheduled_date.desc(), MedicationLog.id.desc()).all()
    return render_template('history.html', logs=logs)


@app.route('/caregiver', methods=['GET', 'POST'])
@approved_caregiver_required
def caregiver_dashboard():
    patients = User.query.filter_by(role='patient').order_by(User.name).all()
    if request.method == 'POST':
        patient = User.query.filter_by(id=request.form.get('patient_id'), role='patient').first()
        if not patient:
            flash('Choose a valid patient.', 'error')
            return redirect(url_for('caregiver_dashboard'))
        try:
            medication = Medication(
                patient_id=patient.id,
                prescribed_by_id=current_user.id,
                **parse_medication_form(request.form),
            )
            db.session.add(medication)
            db.session.commit()
            flash(f'Medication assigned to {patient.name}.', 'success')
            return redirect(url_for('caregiver_dashboard'))
        except (KeyError, ValueError):
            db.session.rollback()
            flash('Please complete the required medication details.', 'error')
    return render_template('caregiver.html', patients=patients)


@app.route('/api/medicines')
@approved_caregiver_required
def medicine_search():
    query = request.args.get('q', '').strip()
    if len(query) < 2:
        return {'medicines': []}
    try:
        api_url = f'https://rxnav.nlm.nih.gov/REST/drugs.json?name={quote(query)}'
        with urlopen(api_url, timeout=3) as response:
            payload = json.load(response)
        names = {
            concept['name'].strip()
            for group in payload.get('drugGroup', {}).get('conceptGroup', [])
            for concept in group.get('conceptProperties', [])
            if concept.get('name')
        }
        return {'medicines': sorted(names)[:10]}
    except (OSError, ValueError):
        return {'medicines': []}


@app.route('/admin')
@role_required('admin')
def admin_dashboard():
    pending_caregivers = User.query.filter_by(role='caregiver', approved=False).order_by(User.created_at).all()
    all_caregivers = User.query.filter_by(role='caregiver').order_by(User.name).all()
    return render_template('admin.html', pending_caregivers=pending_caregivers, all_caregivers=all_caregivers)


@app.route('/admin/caregivers/<int:user_id>/approve', methods=['POST'])
@role_required('admin')
def approve_caregiver(user_id):
    caregiver = User.query.filter_by(id=user_id, role='caregiver').first_or_404()
    caregiver.approved = True
    db.session.commit()
    flash(f'{caregiver.name} can now sign in as a caregiver.', 'success')
    return redirect(url_for('admin_dashboard'))


with app.app_context():
    db.create_all()
    user_columns = {column['name'] for column in db.inspect(db.engine).get_columns('user')}
    if 'role' not in user_columns:
        db.session.execute(db.text("ALTER TABLE user ADD COLUMN role VARCHAR(20) NOT NULL DEFAULT 'patient'"))
    if 'approved' not in user_columns:
        db.session.execute(db.text('ALTER TABLE user ADD COLUMN approved BOOLEAN NOT NULL DEFAULT 1'))
    medication_columns = {column['name'] for column in db.inspect(db.engine).get_columns('medication')}
    if 'prescribed_by_id' not in medication_columns:
        db.session.execute(db.text('ALTER TABLE medication ADD COLUMN prescribed_by_id INTEGER'))
    if admin_email:
        configured_admin = User.query.filter_by(email=admin_email).first()
        if not configured_admin and admin_password:
            configured_admin = User(
                name='Administrator',
                email=admin_email,
                password_hash=generate_password_hash(admin_password),
                role='admin',
                approved=True,
            )
            db.session.add(configured_admin)
        elif configured_admin:
            configured_admin.role = 'admin'
            configured_admin.approved = True
            if admin_password:
                configured_admin.password_hash = generate_password_hash(admin_password)
    db.session.commit()


if __name__ == '__main__':
    app.run(debug=os.getenv('FLASK_DEBUG', '1') == '1', host='0.0.0.0', port=int(os.getenv('PORT', '5000')))
