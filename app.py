from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from datetime import datetime, timedelta
import sqlite3, os, json, pandas as pd

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'bloodbridge-secret-2024')
app.config['DATABASE'] = os.getenv('DATABASE_PATH', 'bloodbridge.db')
app.config['UPLOAD_FOLDER'] = 'uploads'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# ==================== DB HELPERS ====================
def get_db():
    db = sqlite3.connect(app.config['DATABASE'])
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    return db

def init_db():
    db = get_db()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS donors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            age INTEGER NOT NULL,
            gender TEXT NOT NULL,
            blood_group TEXT NOT NULL,
            city TEXT NOT NULL,
            phone TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            weight REAL DEFAULT 60,
            last_donation TEXT,
            available INTEGER DEFAULT 1,
            hospital TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            verified INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS emergency_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_name TEXT NOT NULL,
            blood_group TEXT NOT NULL,
            city TEXT NOT NULL,
            hospital TEXT NOT NULL,
            contact TEXT NOT NULL,
            urgency TEXT DEFAULT 'Normal',
            units_needed INTEGER DEFAULT 1,
            description TEXT,
            status TEXT DEFAULT 'Active',
            created_at TEXT DEFAULT (datetime('now')),
            created_by INTEGER
        );
        CREATE TABLE IF NOT EXISTS donation_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            donor_id INTEGER NOT NULL,
            hospital TEXT NOT NULL,
            donation_date TEXT DEFAULT (datetime('now')),
            units_donated REAL DEFAULT 1.0
        );
        CREATE TABLE IF NOT EXISTS hospitals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            city TEXT NOT NULL,
            phone TEXT NOT NULL,
            address TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now')),
            verified INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS admins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        );
    """)
    # Default admin
    existing = db.execute("SELECT id FROM admins WHERE email='admin@bloodbridge.ai'").fetchone()
    if not existing:
        db.execute("INSERT INTO admins (email, password_hash) VALUES (?, ?)",
                   ('admin@bloodbridge.ai', generate_password_hash('admin123')))
    db.commit()
    db.close()
    print("DB initialized. Admin: admin@bloodbridge.ai / admin123")

# ==================== BLOOD COMPATIBILITY ====================
COMPAT = {
    'O+':  ['O+','O-'],
    'O-':  ['O-'],
    'A+':  ['A+','A-','O+','O-'],
    'A-':  ['A-','O-'],
    'B+':  ['B+','B-','O+','O-'],
    'B-':  ['B-','O-'],
    'AB+': ['O+','O-','A+','A-','B+','B-','AB+','AB-'],
    'AB-': ['O-','A-','B-','AB-'],
}

def compatible_donors_for(patient_bg):
    return [bg for bg, can_receive_from in COMPAT.items() if patient_bg in [p for p,_ in [(bg, None)]]]

# Who can donate TO patient with patient_bg
DONATE_TO = {
    'O+':  ['O+','O-','A+','A-','B+','B-','AB+','AB-'],
    'O-':  ['O-','A-','B-','AB-'],
    'A+':  ['A+','A-','O+','O-'],
    'A-':  ['A-','O-'],
    'B+':  ['B+','B-','O+','O-'],
    'B-':  ['B-','O-'],
    'AB+': ['AB+','AB-','A+','A-','B+','B-','O+','O-'],
    'AB-': ['AB-','A-','B-','O-'],
}

def compatible_for_patient(patient_bg):
    """Blood types that can donate TO this patient"""
    return DONATE_TO.get(patient_bg, [])

def check_eligibility(age, weight, last_donation=None):
    reasons = []
    eligible = True
    if age < 18 or age > 65:
        eligible = False; reasons.append("Age must be between 18-65 years")
    if weight < 50:
        eligible = False; reasons.append("Minimum weight is 50 kg")
    if last_donation:
        try:
            ld = datetime.strptime(last_donation[:10], '%Y-%m-%d')
            days = (datetime.utcnow() - ld).days
            if days < 56:
                eligible = False; reasons.append(f"Wait {56-days} more days (8 weeks between donations)")
        except: pass
    return eligible, reasons

def match_score(donor_bg, donor_city, donor_available, donor_age, donor_weight, donor_last,
                patient_bg, patient_city):
    score = 0
    if donor_bg in compatible_for_patient(patient_bg): score += 40
    if donor_city.lower() == patient_city.lower(): score += 30
    if donor_available: score += 20
    el, _ = check_eligibility(donor_age, donor_weight or 60, donor_last)
    if el: score += 10
    return score

# ==================== AUTH DECORATORS ====================
def hospital_required(f):
    @wraps(f)
    def dec(*a, **kw):
        if 'hospital_id' not in session:
            return redirect(url_for('hospital_login'))
        return f(*a, **kw)
    return dec

def admin_required(f):
    @wraps(f)
    def dec(*a, **kw):
        if 'admin_id' not in session:
            return redirect(url_for('admin_login'))
        return f(*a, **kw)
    return dec

# ==================== ROUTES ====================
@app.route('/')
def index():
    db = get_db()
    total_donors = db.execute("SELECT COUNT(*) FROM donors").fetchone()[0]
    active_donors = db.execute("SELECT COUNT(*) FROM donors WHERE available=1").fetchone()[0]
    total_hospitals = db.execute("SELECT COUNT(*) FROM hospitals").fetchone()[0]
    emergency_count = db.execute("SELECT COUNT(*) FROM emergency_requests WHERE status='Active'").fetchone()[0]
    recent_reqs = db.execute("SELECT * FROM emergency_requests WHERE status='Active' ORDER BY created_at DESC LIMIT 5").fetchall()
    db.close()
    return render_template('index.html',
        total_donors=total_donors, active_donors=active_donors,
        total_hospitals=total_hospitals, emergency_requests=emergency_count,
        recent_requests=recent_reqs)

# ---- DONOR ----
@app.route('/register-donor', methods=['GET','POST'])
def register_donor():
    if request.method == 'POST':
        d = request.get_json() or request.form
        db = get_db()
        if db.execute("SELECT id FROM donors WHERE phone=?", (d.get('phone'),)).fetchone():
            db.close(); return jsonify({'success':False,'message':'Phone already registered'}), 400
        if db.execute("SELECT id FROM donors WHERE email=?", (d.get('email'),)).fetchone():
            db.close(); return jsonify({'success':False,'message':'Email already registered'}), 400
        age = int(d.get('age', 0))
        if age < 18 or age > 65:
            db.close(); return jsonify({'success':False,'message':'Age must be 18-65'}), 400
        try:
            db.execute("""INSERT INTO donors (name,age,gender,blood_group,city,phone,email,weight,last_donation,available)
                VALUES (?,?,?,?,?,?,?,?,?,1)""",
                (d.get('name'), age, d.get('gender'), d.get('blood_group'),
                 d.get('city'), d.get('phone'), d.get('email'),
                 float(d.get('weight', 60)), d.get('last_donation') or None))
            db.commit()
            db.close()
            return jsonify({'success':True,'message':'Registration successful!'})
        except Exception as e:
            db.close(); return jsonify({'success':False,'message':str(e)}), 500
    return render_template('register_donor.html')

@app.route('/search-donor', methods=['GET','POST'])
def search_donor():
    results = []
    blood_groups = ['O+','O-','A+','A-','B+','B-','AB+','AB-']
    args = request.args if request.method == 'GET' else request.form
    blood_group = args.get('blood_group','')
    patient_blood = args.get('patient_blood','')
    city = args.get('city','')
    availability = args.get('availability','')

    if blood_group or patient_blood or city or availability:
        db = get_db()
        query = "SELECT * FROM donors WHERE 1=1"
        params = []
        search_bg = blood_group
        if patient_blood and not blood_group:
            compatible = compatible_for_patient(patient_blood)
            if compatible:
                placeholders = ','.join('?' * len(compatible))
                query += f" AND blood_group IN ({placeholders})"
                params.extend(compatible)
        elif search_bg:
            query += " AND blood_group=?"
            params.append(search_bg)
        if city:
            query += " AND city LIKE ?"
            params.append(f'%{city}%')
        if availability == 'available':
            query += " AND available=1"
        query += " ORDER BY created_at DESC LIMIT 100"
        rows = db.execute(query, params).fetchall()
        cities = [r[0] for r in db.execute("SELECT DISTINCT city FROM donors ORDER BY city").fetchall()]
        db.close()

        results = [dict(r) for r in rows]
        if patient_blood and city:
            for r in results:
                r['match_score'] = match_score(
                    r['blood_group'], r['city'], r['available'],
                    r['age'], r['weight'], r['last_donation'],
                    patient_blood, city)
            results.sort(key=lambda x: x.get('match_score', 0), reverse=True)
    else:
        db = get_db()
        cities = [r[0] for r in db.execute("SELECT DISTINCT city FROM donors ORDER BY city").fetchall()]
        db.close()

    return render_template('search_donor.html',
        results=results, blood_groups=blood_groups, cities=cities,
        args=args)

@app.route('/donor-detail/<int:donor_id>')
def donor_detail(donor_id):
    db = get_db()
    donor = db.execute("SELECT * FROM donors WHERE id=?", (donor_id,)).fetchone()
    if not donor: db.close(); return "Not found", 404
    donor = dict(donor)
    count = db.execute("SELECT COUNT(*) FROM donation_history WHERE donor_id=?", (donor_id,)).fetchone()[0]
    db.close()
    eligible, reasons = check_eligibility(donor['age'], donor['weight'] or 60, donor['last_donation'])
    # format last_donation for display
    if donor['last_donation']:
        try: donor['last_donation_fmt'] = datetime.strptime(donor['last_donation'][:10], '%Y-%m-%d').strftime('%d %b %Y')
        except: donor['last_donation_fmt'] = donor['last_donation']
    else:
        donor['last_donation_fmt'] = None
    return render_template('donor_detail.html', donor=donor, donation_count=count, eligible=eligible, reasons=reasons)

# ---- EMERGENCY ----
@app.route('/emergency-request', methods=['GET','POST'])
def emergency_request():
    if request.method == 'POST':
        d = request.get_json() or request.form
        db = get_db()
        try:
            db.execute("""INSERT INTO emergency_requests
                (patient_name,blood_group,city,hospital,contact,urgency,units_needed,description,created_by)
                VALUES (?,?,?,?,?,?,?,?,?)""",
                (d.get('patient_name'), d.get('blood_group'), d.get('city'),
                 d.get('hospital'), d.get('contact'), d.get('urgency','Normal'),
                 int(d.get('units_needed',1)), d.get('description'),
                 session.get('hospital_id')))
            db.commit(); db.close()
            return jsonify({'success':True,'message':'Emergency request posted and donors alerted!'})
        except Exception as e:
            db.close(); return jsonify({'success':False,'message':str(e)}), 500
    db = get_db()
    blood_groups = ['O+','O-','A+','A-','B+','B-','AB+','AB-']
    cities = [r[0] for r in db.execute("SELECT DISTINCT city FROM donors ORDER BY city").fetchall()]
    db.close()
    return render_template('emergency_request.html', blood_groups=blood_groups, cities=cities)

@app.route('/emergency-board')
def emergency_board():
    db = get_db()
    reqs = db.execute("SELECT * FROM emergency_requests WHERE status='Active' ORDER BY created_at DESC").fetchall()
    db.close()
    return render_template('emergency_board.html', requests=[dict(r) for r in reqs])

# ---- HOSPITAL ----
@app.route('/hospital-register', methods=['GET','POST'])
def hospital_register():
    if request.method == 'POST':
        d = request.get_json() or request.form
        db = get_db()
        if db.execute("SELECT id FROM hospitals WHERE email=?", (d.get('email'),)).fetchone():
            db.close(); return jsonify({'success':False,'message':'Email already registered'}), 400
        try:
            db.execute("INSERT INTO hospitals (name,email,password_hash,city,phone,address) VALUES (?,?,?,?,?,?)",
                (d.get('name'), d.get('email'), generate_password_hash(d.get('password')),
                 d.get('city'), d.get('phone'), d.get('address')))
            db.commit(); db.close()
            return jsonify({'success':True,'message':'Hospital registered!'})
        except Exception as e:
            db.close(); return jsonify({'success':False,'message':str(e)}), 500
    return render_template('hospital_register.html')

@app.route('/hospital-login', methods=['GET','POST'])
def hospital_login():
    if request.method == 'POST':
        d = request.get_json() or request.form
        db = get_db()
        h = db.execute("SELECT * FROM hospitals WHERE email=?", (d.get('email'),)).fetchone()
        db.close()
        if h and check_password_hash(h['password_hash'], d.get('password','')):
            session['hospital_id'] = h['id']
            session['hospital_name'] = h['name']
            return jsonify({'success':True,'message':'Login successful!'})
        return jsonify({'success':False,'message':'Invalid credentials'}), 401
    return render_template('hospital_login.html')

@app.route('/hospital-dashboard')
@hospital_required
def hospital_dashboard():
    db = get_db()
    h = dict(db.execute("SELECT * FROM hospitals WHERE id=?", (session['hospital_id'],)).fetchone())
    total_donors = db.execute("SELECT COUNT(*) FROM donors WHERE hospital=?", (h['name'],)).fetchone()[0]
    total_reqs = db.execute("SELECT COUNT(*) FROM emergency_requests WHERE created_by=?", (h['id'],)).fetchone()[0]
    active_reqs = db.execute("SELECT COUNT(*) FROM emergency_requests WHERE created_by=? AND status='Active'", (h['id'],)).fetchone()[0]
    reqs = db.execute("SELECT * FROM emergency_requests WHERE created_by=? ORDER BY created_at DESC", (h['id'],)).fetchall()
    db.close()
    return render_template('hospital_dashboard.html',
        hospital=h, total_donors=total_donors, total_requests=total_reqs,
        active_requests=active_reqs, requests=[dict(r) for r in reqs])

@app.route('/hospital-upload', methods=['GET','POST'])
@hospital_required
def hospital_upload():
    db = get_db()
    h = dict(db.execute("SELECT * FROM hospitals WHERE id=?", (session['hospital_id'],)).fetchone())
    db.close()
    if request.method == 'POST':
        f = request.files.get('file')
        if not f or not f.filename.endswith('.xlsx'):
            return jsonify({'success':False,'message':'Only .xlsx files allowed'}), 400
        try:
            df = pd.read_excel(f)
            df.columns = [c.strip().lower() for c in df.columns]
            required = ['name','blood_group','city','phone']
            missing = [c for c in required if c not in df.columns]
            if missing:
                return jsonify({'success':False,'message':f'Missing columns: {", ".join(missing)}'}), 400
            db = get_db()
            added = dupes = 0
            for _, row in df.iterrows():
                phone = str(row.get('phone','')).strip().split('.')[0]
                if not phone: continue
                if db.execute("SELECT id FROM donors WHERE phone=?", (phone,)).fetchone():
                    dupes += 1; continue
                email = str(row.get('email', f'donor_{phone}@bloodbridge.local')).strip()
                if db.execute("SELECT id FROM donors WHERE email=?", (email,)).fetchone():
                    email = f'donor_{phone}_{added}@bloodbridge.local'
                try:
                    age = int(float(row.get('age', 30)))
                    weight = float(row.get('weight', 60))
                    avail = str(row.get('available','yes')).lower() in ['yes','true','1','y']
                    ld = None
                    if 'last_donation' in row and pd.notna(row['last_donation']):
                        try: ld = pd.to_datetime(row['last_donation']).strftime('%Y-%m-%d')
                        except: pass
                    db.execute("""INSERT INTO donors (name,age,gender,blood_group,city,phone,email,weight,last_donation,available,hospital)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                        (str(row['name']), age, str(row.get('gender','Not specified')),
                         str(row['blood_group']), str(row['city']), phone, email,
                         weight, ld, 1 if avail else 0, h['name']))
                    added += 1
                except: continue
            db.commit(); db.close()
            return jsonify({'success':True,'message':f'Uploaded {added} donors, {dupes} duplicates skipped.','uploaded':added,'duplicates':dupes})
        except Exception as e:
            return jsonify({'success':False,'message':str(e)}), 500
    return render_template('hospital_upload.html', hospital=h)

@app.route('/hospital-logout')
def hospital_logout():
    session.pop('hospital_id', None); session.pop('hospital_name', None)
    return redirect(url_for('index'))

# ---- ANALYTICS ----
@app.route('/analytics')
def analytics():
    db = get_db()
    total_donors = db.execute("SELECT COUNT(*) FROM donors").fetchone()[0]
    active_donors = db.execute("SELECT COUNT(*) FROM donors WHERE available=1").fetchone()[0]
    total_hospitals = db.execute("SELECT COUNT(*) FROM hospitals").fetchone()[0]
    total_donations = db.execute("SELECT COUNT(*) FROM donation_history").fetchone()[0]
    active_requests = db.execute("SELECT COUNT(*) FROM emergency_requests WHERE status='Active'").fetchone()[0]

    blood_dist = db.execute("SELECT blood_group, COUNT(*) FROM donors GROUP BY blood_group").fetchall()
    city_dist = db.execute("SELECT city, COUNT(*) FROM donors GROUP BY city ORDER BY COUNT(*) DESC LIMIT 10").fetchall()
    urgency_dist = db.execute("SELECT urgency, COUNT(*) FROM emergency_requests GROUP BY urgency").fetchall()

    # Monthly donations (last 6 months)
    six_months_ago = (datetime.utcnow() - timedelta(days=180)).strftime('%Y-%m-%d')
    monthly_raw = db.execute("""
        SELECT strftime('%Y-%m', donation_date) as month, COUNT(*) as cnt
        FROM donation_history WHERE donation_date >= ?
        GROUP BY month ORDER BY month
    """, (six_months_ago,)).fetchall()
    db.close()

    blood_chart = {r[0]: r[1] for r in blood_dist}
    city_chart = {r[0]: r[1] for r in city_dist}
    urgency_chart = {r[0]: r[1] for r in urgency_dist}
    monthly_data = {}
    for row in monthly_raw:
        try:
            dt = datetime.strptime(row[0], '%Y-%m')
            monthly_data[dt.strftime('%b %Y')] = row[1]
        except: pass

    return render_template('analytics.html',
        total_donors=total_donors, active_donors=active_donors,
        total_hospitals=total_hospitals, total_donations=total_donations,
        active_requests=active_requests,
        blood_chart_data=json.dumps(blood_chart),
        city_chart_data=json.dumps(city_chart),
        monthly_data=json.dumps(monthly_data),
        urgency_chart_data=json.dumps(urgency_chart))

# ---- ADMIN ----
@app.route('/admin-login', methods=['GET','POST'])
def admin_login():
    if request.method == 'POST':
        d = request.get_json() or request.form
        db = get_db()
        a = db.execute("SELECT * FROM admins WHERE email=?", (d.get('email'),)).fetchone()
        db.close()
        if a and check_password_hash(a['password_hash'], d.get('password','')):
            session['admin_id'] = a['id']; session['admin_email'] = a['email']
            return jsonify({'success':True})
        return jsonify({'success':False,'message':'Invalid credentials'}), 401
    return render_template('admin_login.html')

@app.route('/admin-dashboard')
@admin_required
def admin_dashboard():
    db = get_db()
    total_donors = db.execute("SELECT COUNT(*) FROM donors").fetchone()[0]
    total_hospitals = db.execute("SELECT COUNT(*) FROM hospitals").fetchone()[0]
    total_requests = db.execute("SELECT COUNT(*) FROM emergency_requests").fetchone()[0]
    verified_donors = db.execute("SELECT COUNT(*) FROM donors WHERE verified=1").fetchone()[0]
    recent_donors = db.execute("SELECT * FROM donors ORDER BY created_at DESC LIMIT 10").fetchall()
    recent_requests = db.execute("SELECT * FROM emergency_requests ORDER BY created_at DESC LIMIT 10").fetchall()
    db.close()
    return render_template('admin_dashboard.html',
        total_donors=total_donors, total_hospitals=total_hospitals,
        total_requests=total_requests, verified_donors=verified_donors,
        recent_donors=[dict(r) for r in recent_donors],
        recent_requests=[dict(r) for r in recent_requests])

@app.route('/admin-manage-donors')
@admin_required
def admin_manage_donors():
    page = request.args.get('page', 1, type=int)
    per_page = 20
    offset = (page - 1) * per_page
    db = get_db()
    total = db.execute("SELECT COUNT(*) FROM donors").fetchone()[0]
    donors = db.execute("SELECT * FROM donors ORDER BY created_at DESC LIMIT ? OFFSET ?", (per_page, offset)).fetchall()
    db.close()
    total_pages = (total + per_page - 1) // per_page
    return render_template('admin_manage_donors.html',
        donors=[dict(r) for r in donors],
        page=page, total_pages=total_pages, total=total)

@app.route('/admin-donor-delete/<int:donor_id>', methods=['POST'])
@admin_required
def admin_donor_delete(donor_id):
    db = get_db()
    db.execute("DELETE FROM donation_history WHERE donor_id=?", (donor_id,))
    db.execute("DELETE FROM donors WHERE id=?", (donor_id,))
    db.commit(); db.close()
    return jsonify({'success':True,'message':'Donor deleted'})

@app.route('/admin-manage-requests')
@admin_required
def admin_manage_requests():
    page = request.args.get('page', 1, type=int)
    per_page = 20
    offset = (page - 1) * per_page
    db = get_db()
    total = db.execute("SELECT COUNT(*) FROM emergency_requests").fetchone()[0]
    reqs = db.execute("SELECT * FROM emergency_requests ORDER BY created_at DESC LIMIT ? OFFSET ?", (per_page, offset)).fetchall()
    db.close()
    total_pages = (total + per_page - 1) // per_page
    return render_template('admin_manage_requests.html',
        requests=[dict(r) for r in reqs],
        page=page, total_pages=total_pages)

@app.route('/admin-request-delete/<int:req_id>', methods=['POST'])
@admin_required
def admin_request_delete(req_id):
    db = get_db()
    db.execute("DELETE FROM emergency_requests WHERE id=?", (req_id,))
    db.commit(); db.close()
    return jsonify({'success':True,'message':'Request deleted'})

@app.route('/admin-logout')
def admin_logout():
    session.pop('admin_id', None); session.pop('admin_email', None)
    return redirect(url_for('index'))

# ---- API ----
@app.route('/api/blood-compatibility/<blood_group>')
def api_blood_compat(blood_group):
    compatible = compatible_for_patient(blood_group)
    return jsonify({'blood_group': blood_group, 'compatible': compatible})

@app.route('/api/donor-eligibility', methods=['POST'])
def api_eligibility():
    d = request.get_json()
    el, reasons = check_eligibility(int(d.get('age',0)), float(d.get('weight',50)), d.get('last_donation'))
    return jsonify({'eligible': el, 'reasons': reasons})

# ---- ERRORS ----
@app.errorhandler(404)
def not_found(e): return render_template('404.html'), 404
@app.errorhandler(500)
def server_error(e): return render_template('500.html'), 500

if __name__ == '__main__':
    init_db()
    app.run(debug=False, host='0.0.0.0', port=5000)
