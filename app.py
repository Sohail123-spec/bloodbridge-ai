from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from datetime import datetime, timedelta
import os, json, pandas as pd

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'bloodbridge-secret-2024')
app.config['UPLOAD_FOLDER'] = 'uploads'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# ==================== DATABASE ABSTRACTION ====================
# Supports both PostgreSQL (Render) and SQLite (local dev)
DATABASE_URL = os.getenv('DATABASE_URL', '')

# Render gives postgres:// but psycopg2 needs postgresql://
if DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)

USE_POSTGRES = DATABASE_URL.startswith('postgresql://')

def get_db():
    if USE_POSTGRES:
        import psycopg2
        import psycopg2.extras
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = False
        return conn
    else:
        import sqlite3
        conn = sqlite3.connect(os.getenv('DATABASE_PATH', 'bloodbridge.db'))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

def q(sql):
    """Convert SQLite ? placeholders to PostgreSQL %s"""
    if USE_POSTGRES:
        return sql.replace('?', '%s')
    return sql

def fetchall(cursor):
    rows = cursor.fetchall()
    if USE_POSTGRES:
        return [dict(r) for r in rows]
    return [dict(r) for r in rows]

def fetchone(cursor):
    row = cursor.fetchone()
    if row is None:
        return None
    if USE_POSTGRES:
        return dict(row)
    return dict(row)

def db_execute(conn, sql, params=()):
    """Execute with correct cursor type"""
    if USE_POSTGRES:
        import psycopg2.extras
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    else:
        cur = conn.cursor()
    cur.execute(q(sql), params)
    return cur

def init_db():
    conn = get_db()
    if USE_POSTGRES:
        import psycopg2.extras
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        # PostgreSQL schema
        statements = [
            """CREATE TABLE IF NOT EXISTS donors (
                id SERIAL PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                age INTEGER NOT NULL,
                gender VARCHAR(10) NOT NULL,
                blood_group VARCHAR(5) NOT NULL,
                city VARCHAR(50) NOT NULL,
                phone VARCHAR(15) UNIQUE NOT NULL,
                email VARCHAR(100) UNIQUE NOT NULL,
                weight REAL DEFAULT 60,
                last_donation DATE,
                available INTEGER DEFAULT 1,
                hospital VARCHAR(100),
                created_at TIMESTAMP DEFAULT NOW(),
                verified INTEGER DEFAULT 1
            )""",
            """CREATE TABLE IF NOT EXISTS emergency_requests (
                id SERIAL PRIMARY KEY,
                patient_name VARCHAR(100) NOT NULL,
                blood_group VARCHAR(5) NOT NULL,
                city VARCHAR(50) NOT NULL,
                hospital VARCHAR(100) NOT NULL,
                contact VARCHAR(15) NOT NULL,
                urgency VARCHAR(20) DEFAULT 'Normal',
                units_needed INTEGER DEFAULT 1,
                description TEXT,
                status VARCHAR(20) DEFAULT 'Active',
                created_at TIMESTAMP DEFAULT NOW(),
                created_by INTEGER
            )""",
            """CREATE TABLE IF NOT EXISTS donation_history (
                id SERIAL PRIMARY KEY,
                donor_id INTEGER NOT NULL,
                hospital VARCHAR(100) NOT NULL,
                donation_date TIMESTAMP DEFAULT NOW(),
                units_donated REAL DEFAULT 1.0
            )""",
            """CREATE TABLE IF NOT EXISTS hospitals (
                id SERIAL PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                email VARCHAR(100) UNIQUE NOT NULL,
                password_hash VARCHAR(200) NOT NULL,
                city VARCHAR(50) NOT NULL,
                phone VARCHAR(15) NOT NULL,
                address TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT NOW(),
                verified INTEGER DEFAULT 1
            )""",
            """CREATE TABLE IF NOT EXISTS certificate_requests (
                id SERIAL PRIMARY KEY,
                donor_id INTEGER NOT NULL,
                donor_name VARCHAR(100) NOT NULL,
                blood_group VARCHAR(5) NOT NULL,
                hospital VARCHAR(100) NOT NULL,
                donation_date DATE NOT NULL,
                photo_base64 TEXT NOT NULL,
                photo_mime VARCHAR(30) DEFAULT 'image/jpeg',
                status VARCHAR(20) DEFAULT 'Pending',
                admin_note TEXT,
                requested_at TIMESTAMP DEFAULT NOW(),
                approved_at TIMESTAMP
            )""",
            """CREATE TABLE IF NOT EXISTS admins (
                id SERIAL PRIMARY KEY,
                email VARCHAR(100) UNIQUE NOT NULL,
                password_hash VARCHAR(200) NOT NULL,
                created_at TIMESTAMP DEFAULT NOW()
            )"""
        ]
        for stmt in statements:
            cur.execute(stmt)
        # Default admin
        cur.execute("SELECT id FROM admins WHERE email='admin@bloodbridge.ai'")
        if not cur.fetchone():
            cur.execute("INSERT INTO admins (email, password_hash) VALUES (%s, %s)",
                ('admin@bloodbridge.ai', generate_password_hash('admin123')))
        conn.commit()
        cur.close()
    else:
        import sqlite3
        cur = conn.cursor()
        schema = """
            CREATE TABLE IF NOT EXISTS donors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL, age INTEGER NOT NULL, gender TEXT NOT NULL,
                blood_group TEXT NOT NULL, city TEXT NOT NULL,
                phone TEXT UNIQUE NOT NULL, email TEXT UNIQUE NOT NULL,
                weight REAL DEFAULT 60, last_donation TEXT,
                available INTEGER DEFAULT 1, hospital TEXT,
                created_at TEXT DEFAULT (datetime('now')), verified INTEGER DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS emergency_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                patient_name TEXT NOT NULL, blood_group TEXT NOT NULL,
                city TEXT NOT NULL, hospital TEXT NOT NULL, contact TEXT NOT NULL,
                urgency TEXT DEFAULT 'Normal', units_needed INTEGER DEFAULT 1,
                description TEXT, status TEXT DEFAULT 'Active',
                created_at TEXT DEFAULT (datetime('now')), created_by INTEGER
            );
            CREATE TABLE IF NOT EXISTS donation_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                donor_id INTEGER NOT NULL, hospital TEXT NOT NULL,
                donation_date TEXT DEFAULT (datetime('now')), units_donated REAL DEFAULT 1.0
            );
            CREATE TABLE IF NOT EXISTS hospitals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL, email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL, city TEXT NOT NULL,
                phone TEXT NOT NULL, address TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now')), verified INTEGER DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS certificate_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                donor_id INTEGER NOT NULL, donor_name TEXT NOT NULL,
                blood_group TEXT NOT NULL, hospital TEXT NOT NULL,
                donation_date TEXT NOT NULL, photo_base64 TEXT NOT NULL,
                photo_mime TEXT DEFAULT 'image/jpeg', status TEXT DEFAULT 'Pending',
                admin_note TEXT, requested_at TEXT DEFAULT (datetime('now')),
                approved_at TEXT
            );
            CREATE TABLE IF NOT EXISTS admins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            );
        """
        cur.executescript(schema)
        cur.execute("SELECT id FROM admins WHERE email='admin@bloodbridge.ai'")
        if not cur.fetchone():
            cur.execute("INSERT INTO admins (email, password_hash) VALUES (?, ?)",
                ('admin@bloodbridge.ai', generate_password_hash('admin123')))
        conn.commit()
    conn.close()
    print(f"DB initialized ({'PostgreSQL' if USE_POSTGRES else 'SQLite'}). Admin: admin@bloodbridge.ai / admin123")

# ==================== JINJA2 DATE FILTER ====================
@app.template_filter('dateformat')
def dateformat(value, fmt='%d %b %Y, %I:%M %p'):
    if not value: return '-'
    if isinstance(value, (datetime,)): return value.strftime(fmt)
    try:
        import datetime as dt
        if isinstance(value, dt.date): return value.strftime(fmt)
    except: pass
    for f in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d'):
        try: return datetime.strptime(str(value)[:19], f).strftime(fmt)
        except: continue
    return str(value)[:16]

# ==================== BLOOD COMPATIBILITY ====================
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
    return DONATE_TO.get(patient_bg, [])

def check_eligibility(age, weight, last_donation=None):
    reasons = []; eligible = True
    if age < 18 or age > 65:
        eligible = False; reasons.append("Age must be between 18-65 years")
    if weight < 50:
        eligible = False; reasons.append("Minimum weight is 50 kg")
    if last_donation:
        try:
            ld = last_donation if isinstance(last_donation, datetime) else datetime.strptime(str(last_donation)[:10], '%Y-%m-%d')
            days = (datetime.utcnow() - ld).days
            if days < 56:
                eligible = False; reasons.append(f"Wait {56-days} more days (8 weeks between donations)")
        except: pass
    return eligible, reasons

def match_score(donor_bg, donor_city, donor_available, donor_age, donor_weight, donor_last, patient_bg, patient_city):
    score = 0
    if donor_bg in compatible_for_patient(patient_bg): score += 40
    if str(donor_city).lower() == str(patient_city).lower(): score += 30
    if donor_available: score += 20
    el, _ = check_eligibility(donor_age, donor_weight or 60, donor_last)
    if el: score += 10
    return score

# ==================== AUTH DECORATORS ====================
def hospital_required(f):
    @wraps(f)
    def dec(*a, **kw):
        if 'hospital_id' not in session: return redirect(url_for('hospital_login'))
        return f(*a, **kw)
    return dec

def admin_required(f):
    @wraps(f)
    def dec(*a, **kw):
        if 'admin_id' not in session: return redirect(url_for('admin_login'))
        return f(*a, **kw)
    return dec

# ==================== ROUTES ====================

@app.route('/')
def index():
    conn = get_db()
    cur = db_execute(conn, "SELECT COUNT(*) as c FROM donors"); total_donors = fetchone(cur)['c']
    cur = db_execute(conn, "SELECT COUNT(*) as c FROM donors WHERE available=1"); active_donors = fetchone(cur)['c']
    cur = db_execute(conn, "SELECT COUNT(*) as c FROM hospitals"); total_hospitals = fetchone(cur)['c']
    cur = db_execute(conn, "SELECT COUNT(*) as c FROM emergency_requests WHERE status='Active'"); emergency_count = fetchone(cur)['c']
    cur = db_execute(conn, "SELECT * FROM emergency_requests WHERE status='Active' ORDER BY created_at DESC LIMIT 5")
    recent_reqs = fetchall(cur)
    conn.close()
    return render_template('index.html', total_donors=total_donors, active_donors=active_donors,
        total_hospitals=total_hospitals, emergency_requests=emergency_count, recent_requests=recent_reqs)

# ---- DONOR ----
@app.route('/register-donor', methods=['GET','POST'])
def register_donor():
    if request.method == 'POST':
        d = request.get_json() or request.form
        conn = get_db()
        cur = db_execute(conn, "SELECT id FROM donors WHERE phone=?", (d.get('phone'),))
        if fetchone(cur): conn.close(); return jsonify({'success':False,'message':'Phone already registered'}), 400
        cur = db_execute(conn, "SELECT id FROM donors WHERE email=?", (d.get('email'),))
        if fetchone(cur): conn.close(); return jsonify({'success':False,'message':'Email already registered'}), 400
        age = int(d.get('age', 0))
        if age < 18 or age > 65: conn.close(); return jsonify({'success':False,'message':'Age must be 18-65'}), 400
        try:
            db_execute(conn, """INSERT INTO donors (name,age,gender,blood_group,city,phone,email,weight,last_donation,available)
                VALUES (?,?,?,?,?,?,?,?,?,1)""",
                (d.get('name'), age, d.get('gender'), d.get('blood_group'), d.get('city'),
                 d.get('phone'), d.get('email'), float(d.get('weight',60)), d.get('last_donation') or None))
            conn.commit(); conn.close()
            return jsonify({'success':True,'message':'Registration successful!'})
        except Exception as e:
            conn.rollback(); conn.close(); return jsonify({'success':False,'message':str(e)}), 500
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

    conn = get_db()
    if blood_group or patient_blood or city or availability:
        query = "SELECT * FROM donors WHERE 1=1"
        params = []
        if patient_blood and not blood_group:
            compatible = compatible_for_patient(patient_blood)
            if compatible:
                placeholders = ','.join(['?']*len(compatible))
                query += f" AND blood_group IN ({placeholders})"
                params.extend(compatible)
        elif blood_group:
            query += " AND blood_group=?"; params.append(blood_group)
        if city:
            if USE_POSTGRES: query += " AND city ILIKE ?"
            else: query += " AND city LIKE ?"
            params.append(f'%{city}%')
        if availability == 'available': query += " AND available=1"
        query += " ORDER BY created_at DESC LIMIT 100"
        cur = db_execute(conn, query, params)
        results = fetchall(cur)
        if patient_blood and city:
            for r in results:
                r['match_score'] = match_score(r['blood_group'], r['city'], r['available'],
                    r['age'], r['weight'], r['last_donation'], patient_blood, city)
            results.sort(key=lambda x: x.get('match_score',0), reverse=True)

    cur = db_execute(conn, "SELECT DISTINCT city FROM donors ORDER BY city")
    cities = [r['city'] for r in fetchall(cur)]
    conn.close()
    return render_template('search_donor.html', results=results, blood_groups=blood_groups, cities=cities, args=args)

@app.route('/donor-detail/<int:donor_id>')
def donor_detail(donor_id):
    conn = get_db()
    cur = db_execute(conn, "SELECT * FROM donors WHERE id=?", (donor_id,))
    donor = fetchone(cur)
    if not donor: conn.close(); return "Not found", 404
    cur = db_execute(conn, "SELECT COUNT(*) as c FROM donation_history WHERE donor_id=?", (donor_id,))
    count = fetchone(cur)['c']
    conn.close()
    eligible, reasons = check_eligibility(donor['age'], donor['weight'] or 60, donor['last_donation'])
    ld = donor['last_donation']
    if ld:
        try: donor['last_donation_fmt'] = ld.strftime('%d %b %Y') if hasattr(ld,'strftime') else datetime.strptime(str(ld)[:10],'%Y-%m-%d').strftime('%d %b %Y')
        except: donor['last_donation_fmt'] = str(ld)
    else: donor['last_donation_fmt'] = None
    return render_template('donor_detail.html', donor=donor, donation_count=count, eligible=eligible, reasons=reasons)

# ---- EMERGENCY ----
@app.route('/emergency-request', methods=['GET','POST'])
def emergency_request():
    if request.method == 'POST':
        d = request.get_json() or request.form
        conn = get_db()
        try:
            db_execute(conn, """INSERT INTO emergency_requests
                (patient_name,blood_group,city,hospital,contact,urgency,units_needed,description,created_by)
                VALUES (?,?,?,?,?,?,?,?,?)""",
                (d.get('patient_name'), d.get('blood_group'), d.get('city'), d.get('hospital'),
                 d.get('contact'), d.get('urgency','Normal'), int(d.get('units_needed',1)),
                 d.get('description'), session.get('hospital_id')))
            conn.commit(); conn.close()
            return jsonify({'success':True,'message':'Emergency request posted and donors alerted!'})
        except Exception as e:
            conn.rollback(); conn.close(); return jsonify({'success':False,'message':str(e)}), 500
    conn = get_db()
    cur = db_execute(conn, "SELECT DISTINCT city FROM donors ORDER BY city")
    cities = [r['city'] for r in fetchall(cur)]
    conn.close()
    blood_groups = ['O+','O-','A+','A-','B+','B-','AB+','AB-']
    return render_template('emergency_request.html', blood_groups=blood_groups, cities=cities)

@app.route('/emergency-board')
def emergency_board():
    conn = get_db()
    cur = db_execute(conn, "SELECT * FROM emergency_requests WHERE status='Active' ORDER BY created_at DESC")
    reqs = fetchall(cur); conn.close()
    return render_template('emergency_board.html', requests=reqs)

# ---- HOSPITAL ----
@app.route('/hospital-register', methods=['GET','POST'])
def hospital_register():
    if request.method == 'POST':
        d = request.get_json() or request.form
        conn = get_db()
        cur = db_execute(conn, "SELECT id FROM hospitals WHERE email=?", (d.get('email'),))
        if fetchone(cur): conn.close(); return jsonify({'success':False,'message':'Email already registered'}), 400
        try:
            db_execute(conn, "INSERT INTO hospitals (name,email,password_hash,city,phone,address) VALUES (?,?,?,?,?,?)",
                (d.get('name'), d.get('email'), generate_password_hash(d.get('password')),
                 d.get('city'), d.get('phone'), d.get('address')))
            conn.commit(); conn.close()
            return jsonify({'success':True,'message':'Hospital registered!'})
        except Exception as e:
            conn.rollback(); conn.close(); return jsonify({'success':False,'message':str(e)}), 500
    return render_template('hospital_register.html')

@app.route('/hospital-login', methods=['GET','POST'])
def hospital_login():
    if request.method == 'POST':
        d = request.get_json() or request.form
        conn = get_db()
        cur = db_execute(conn, "SELECT * FROM hospitals WHERE email=?", (d.get('email'),))
        h = fetchone(cur); conn.close()
        if h and check_password_hash(h['password_hash'], d.get('password','')):
            session['hospital_id'] = h['id']; session['hospital_name'] = h['name']
            return jsonify({'success':True,'message':'Login successful!'})
        return jsonify({'success':False,'message':'Invalid credentials'}), 401
    return render_template('hospital_login.html')

@app.route('/hospital-dashboard')
@hospital_required
def hospital_dashboard():
    conn = get_db()
    cur = db_execute(conn, "SELECT * FROM hospitals WHERE id=?", (session['hospital_id'],))
    h = fetchone(cur)
    cur = db_execute(conn, "SELECT COUNT(*) as c FROM donors WHERE hospital=?", (h['name'],))
    total_donors = fetchone(cur)['c']
    cur = db_execute(conn, "SELECT COUNT(*) as c FROM emergency_requests WHERE created_by=?", (h['id'],))
    total_reqs = fetchone(cur)['c']
    cur = db_execute(conn, "SELECT COUNT(*) as c FROM emergency_requests WHERE created_by=? AND status='Active'", (h['id'],))
    active_reqs = fetchone(cur)['c']
    cur = db_execute(conn, "SELECT * FROM emergency_requests WHERE created_by=? ORDER BY created_at DESC", (h['id'],))
    reqs = fetchall(cur); conn.close()
    return render_template('hospital_dashboard.html', hospital=h, total_donors=total_donors,
        total_requests=total_reqs, active_requests=active_reqs, requests=reqs)

@app.route('/hospital-upload', methods=['GET','POST'])
@hospital_required
def hospital_upload():
    conn = get_db()
    cur = db_execute(conn, "SELECT * FROM hospitals WHERE id=?", (session['hospital_id'],))
    h = fetchone(cur); conn.close()
    if request.method == 'POST':
        f = request.files.get('file')
        if not f or not f.filename.endswith('.xlsx'):
            return jsonify({'success':False,'message':'Only .xlsx files allowed'}), 400
        try:
            df = pd.read_excel(f)
            df.columns = [c.strip().lower() for c in df.columns]
            required = ['name','blood_group','city','phone']
            missing = [c for c in required if c not in df.columns]
            if missing: return jsonify({'success':False,'message':f'Missing: {", ".join(missing)}'}), 400
            conn = get_db(); added = dupes = 0
            for _, row in df.iterrows():
                phone = str(row.get('phone','')).strip().split('.')[0]
                if not phone: continue
                cur = db_execute(conn, "SELECT id FROM donors WHERE phone=?", (phone,))
                if fetchone(cur): dupes += 1; continue
                email = str(row.get('email', f'donor_{phone}@bloodbridge.local')).strip()
                cur = db_execute(conn, "SELECT id FROM donors WHERE email=?", (email,))
                if fetchone(cur): email = f'donor_{phone}_{added}@bloodbridge.local'
                try:
                    age = int(float(row.get('age',30)))
                    weight = float(row.get('weight',60))
                    avail = str(row.get('available','yes')).lower() in ['yes','true','1','y']
                    ld = None
                    if 'last_donation' in row and pd.notna(row['last_donation']):
                        try: ld = pd.to_datetime(row['last_donation']).strftime('%Y-%m-%d')
                        except: pass
                    db_execute(conn, """INSERT INTO donors (name,age,gender,blood_group,city,phone,email,weight,last_donation,available,hospital)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                        (str(row['name']), age, str(row.get('gender','Not specified')),
                         str(row['blood_group']), str(row['city']), phone, email,
                         weight, ld, 1 if avail else 0, h['name']))
                    added += 1
                except: continue
            conn.commit(); conn.close()
            return jsonify({'success':True,'message':f'Uploaded {added} donors, {dupes} duplicates skipped.','uploaded':added,'duplicates':dupes})
        except Exception as e:
            return jsonify({'success':False,'message':str(e)}), 500
    return render_template('hospital_upload.html', hospital=h)

@app.route('/hospital-logout')
def hospital_logout():
    session.pop('hospital_id',None); session.pop('hospital_name',None)
    return redirect(url_for('index'))

# ---- ANALYTICS ----
@app.route('/analytics')
def analytics():
    conn = get_db()
    def count(sql, p=()): cur = db_execute(conn, sql, p); return fetchone(cur)['c']
    total_donors   = count("SELECT COUNT(*) as c FROM donors")
    active_donors  = count("SELECT COUNT(*) as c FROM donors WHERE available=1")
    total_hospitals= count("SELECT COUNT(*) as c FROM hospitals")
    total_donations= count("SELECT COUNT(*) as c FROM donation_history")
    active_requests= count("SELECT COUNT(*) as c FROM emergency_requests WHERE status='Active'")

    cur = db_execute(conn, "SELECT blood_group, COUNT(*) as c FROM donors GROUP BY blood_group")
    blood_chart = {r['blood_group']:r['c'] for r in fetchall(cur)}

    cur = db_execute(conn, "SELECT city, COUNT(*) as c FROM donors GROUP BY city ORDER BY c DESC LIMIT 10")
    city_chart = {r['city']:r['c'] for r in fetchall(cur)}

    cur = db_execute(conn, "SELECT urgency, COUNT(*) as c FROM emergency_requests GROUP BY urgency")
    urgency_chart = {r['urgency']:r['c'] for r in fetchall(cur)}

    # Monthly donations last 6 months
    if USE_POSTGRES:
        cur = db_execute(conn, """
            SELECT TO_CHAR(DATE_TRUNC('month', donation_date), 'Mon YYYY') as month, COUNT(*) as c
            FROM donation_history
            WHERE donation_date >= NOW() - INTERVAL '6 months'
            GROUP BY DATE_TRUNC('month', donation_date)
            ORDER BY DATE_TRUNC('month', donation_date)""")
    else:
        cur = db_execute(conn, """
            SELECT strftime('%m %Y', donation_date) as month, COUNT(*) as c
            FROM donation_history
            WHERE donation_date >= date('now','-6 months')
            GROUP BY strftime('%Y-%m', donation_date)
            ORDER BY strftime('%Y-%m', donation_date)""")
    monthly_data = {r['month']:r['c'] for r in fetchall(cur)}
    conn.close()

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
        conn = get_db()
        cur = db_execute(conn, "SELECT * FROM admins WHERE email=?", (d.get('email'),))
        a = fetchone(cur); conn.close()
        if a and check_password_hash(a['password_hash'], d.get('password','')):
            session['admin_id'] = a['id']; session['admin_email'] = a['email']
            return jsonify({'success':True})
        return jsonify({'success':False,'message':'Invalid credentials'}), 401
    return render_template('admin_login.html')

@app.route('/admin-dashboard')
@admin_required
def admin_dashboard():
    conn = get_db()
    def count(sql): cur=db_execute(conn,sql); return fetchone(cur)['c']
    total_donors   = count("SELECT COUNT(*) as c FROM donors")
    total_hospitals= count("SELECT COUNT(*) as c FROM hospitals")
    total_requests = count("SELECT COUNT(*) as c FROM emergency_requests")
    verified_donors= count("SELECT COUNT(*) as c FROM donors WHERE verified=1")
    pending_certs  = count("SELECT COUNT(*) as c FROM certificate_requests WHERE status='Pending'")
    cur = db_execute(conn, "SELECT * FROM donors ORDER BY created_at DESC LIMIT 10")
    recent_donors = fetchall(cur)
    cur = db_execute(conn, "SELECT * FROM emergency_requests ORDER BY created_at DESC LIMIT 10")
    recent_requests = fetchall(cur)
    conn.close()
    return render_template('admin_dashboard.html', total_donors=total_donors,
        total_hospitals=total_hospitals, total_requests=total_requests,
        verified_donors=verified_donors, pending_certs=pending_certs,
        recent_donors=recent_donors, recent_requests=recent_requests)

@app.route('/admin-change-password', methods=['GET','POST'])
@admin_required
def admin_change_password():
    if request.method == 'POST':
        d = request.get_json() or request.form
        conn = get_db()
        cur = db_execute(conn, "SELECT * FROM admins WHERE id=?", (session['admin_id'],))
        admin = fetchone(cur)
        if not check_password_hash(admin['password_hash'], d.get('current_password','')):
            conn.close(); return jsonify({'success':False,'message':'Current password is incorrect'}), 400
        new_pw = d.get('new_password','')
        if len(new_pw) < 6:
            conn.close(); return jsonify({'success':False,'message':'New password must be at least 6 characters'}), 400
        db_execute(conn, "UPDATE admins SET password_hash=? WHERE id=?",
            (generate_password_hash(new_pw), session['admin_id']))
        conn.commit(); conn.close()
        return jsonify({'success':True,'message':'Password changed successfully!'})
    return render_template('admin_change_password.html')

@app.route('/admin-manage-donors')
@admin_required
def admin_manage_donors():
    page = request.args.get('page',1,type=int); per_page = 20; offset = (page-1)*per_page
    conn = get_db()
    cur = db_execute(conn, "SELECT COUNT(*) as c FROM donors"); total = fetchone(cur)['c']
    cur = db_execute(conn, "SELECT * FROM donors ORDER BY created_at DESC LIMIT ? OFFSET ?", (per_page, offset))
    donors = fetchall(cur); conn.close()
    total_pages = (total+per_page-1)//per_page
    return render_template('admin_manage_donors.html', donors=donors, page=page, total_pages=total_pages, total=total)

@app.route('/admin-donor-delete/<int:donor_id>', methods=['POST'])
@admin_required
def admin_donor_delete(donor_id):
    conn = get_db()
    db_execute(conn, "DELETE FROM donation_history WHERE donor_id=?", (donor_id,))
    db_execute(conn, "DELETE FROM donors WHERE id=?", (donor_id,))
    conn.commit(); conn.close()
    return jsonify({'success':True,'message':'Donor deleted'})

@app.route('/admin-manage-requests')
@admin_required
def admin_manage_requests():
    page = request.args.get('page',1,type=int); per_page = 20; offset = (page-1)*per_page
    conn = get_db()
    cur = db_execute(conn, "SELECT COUNT(*) as c FROM emergency_requests"); total = fetchone(cur)['c']
    cur = db_execute(conn, "SELECT * FROM emergency_requests ORDER BY created_at DESC LIMIT ? OFFSET ?", (per_page, offset))
    reqs = fetchall(cur); conn.close()
    total_pages = (total+per_page-1)//per_page
    return render_template('admin_manage_requests.html', requests=reqs, page=page, total_pages=total_pages)

@app.route('/admin-request-delete/<int:req_id>', methods=['POST'])
@admin_required
def admin_request_delete(req_id):
    conn = get_db()
    db_execute(conn, "DELETE FROM emergency_requests WHERE id=?", (req_id,))
    conn.commit(); conn.close()
    return jsonify({'success':True,'message':'Request deleted'})

@app.route('/admin-logout')
def admin_logout():
    session.pop('admin_id',None); session.pop('admin_email',None)
    return redirect(url_for('index'))

# ---- CERTIFICATE REQUESTS ----
@app.route('/request-certificate', methods=['GET','POST'])
def request_certificate():
    if request.method == 'POST':
        import base64
        photo = request.files.get('photo')
        if not photo: return jsonify({'success':False,'message':'Please upload a photo'}), 400
        if photo.mimetype not in {'image/jpeg','image/jpg','image/png','image/webp'}:
            return jsonify({'success':False,'message':'Only JPG, PNG or WEBP allowed'}), 400
        photo_bytes = photo.read()
        if len(photo_bytes) > 5*1024*1024: return jsonify({'success':False,'message':'Image must be under 5MB'}), 400
        photo_b64 = base64.b64encode(photo_bytes).decode('utf-8')
        donor_name    = request.form.get('donor_name','').strip()
        blood_group   = request.form.get('blood_group','').strip()
        hospital      = request.form.get('hospital','').strip()
        donation_date = request.form.get('donation_date','').strip()
        phone         = request.form.get('phone','').strip()
        if not all([donor_name,blood_group,hospital,donation_date,phone]):
            return jsonify({'success':False,'message':'All fields are required'}), 400
        conn = get_db()
        cur = db_execute(conn, "SELECT id FROM donors WHERE phone=?", (phone,))
        donor = fetchone(cur)
        donor_id = donor['id'] if donor else 0
        db_execute(conn, """INSERT INTO certificate_requests
            (donor_id,donor_name,blood_group,hospital,donation_date,photo_base64,photo_mime)
            VALUES (?,?,?,?,?,?,?)""",
            (donor_id,donor_name,blood_group,hospital,donation_date,photo_b64,photo.mimetype))
        conn.commit(); conn.close()
        return jsonify({'success':True,'message':'Request submitted! Admin will review within 24 hours.'})
    blood_groups = ['O+','O-','A+','A-','B+','B-','AB+','AB-']
    return render_template('request_certificate.html', blood_groups=blood_groups)

@app.route('/admin-certificate-requests')
@admin_required
def admin_certificate_requests():
    conn = get_db()
    status_filter = request.args.get('status','Pending')
    cur = db_execute(conn, "SELECT * FROM certificate_requests WHERE status=? ORDER BY requested_at DESC", (status_filter,))
    reqs = fetchall(cur)
    counts = {}
    for s in ['Pending','Approved','Rejected']:
        cur = db_execute(conn, "SELECT COUNT(*) as c FROM certificate_requests WHERE status=?", (s,))
        counts[s] = fetchone(cur)['c']
    conn.close()
    return render_template('admin_cert_requests.html', requests=reqs, status_filter=status_filter, counts=counts)

@app.route('/admin-approve-certificate/<int:req_id>', methods=['POST'])
@admin_required
def admin_approve_certificate(req_id):
    conn = get_db()
    note = request.get_json().get('note','')
    if USE_POSTGRES:
        db_execute(conn, "UPDATE certificate_requests SET status='Approved', approved_at=NOW(), admin_note=? WHERE id=?", (note,req_id))
    else:
        db_execute(conn, "UPDATE certificate_requests SET status='Approved', approved_at=datetime('now'), admin_note=? WHERE id=?", (note,req_id))
    conn.commit(); conn.close()
    return jsonify({'success':True,'certificate_url':f'/certificate/req/{req_id}'})

@app.route('/admin-reject-certificate/<int:req_id>', methods=['POST'])
@admin_required
def admin_reject_certificate(req_id):
    conn = get_db()
    note = request.get_json().get('note','Does not meet requirements.')
    db_execute(conn, "UPDATE certificate_requests SET status='Rejected', admin_note=? WHERE id=?", (note,req_id))
    conn.commit(); conn.close()
    return jsonify({'success':True,'message':'Rejected.'})

@app.route('/certificate/req/<int:req_id>')
def certificate_from_request(req_id):
    conn = get_db()
    cur = db_execute(conn, "SELECT * FROM certificate_requests WHERE id=? AND status='Approved'", (req_id,))
    row = fetchone(cur); conn.close()
    if not row: return render_template('cert_pending.html'), 403
    try:
        dd = row['donation_date']
        row['donation_date_fmt'] = dd.strftime('%d %B %Y') if hasattr(dd,'strftime') else datetime.strptime(str(dd)[:10],'%Y-%m-%d').strftime('%d %B %Y')
    except: row['donation_date_fmt'] = str(row['donation_date'])
    dd_str = str(row['donation_date'])[:10]
    cert_id = f"BBAI-{dd_str[:4]}-{dd_str[5:7]}{dd_str[8:10]}-R{str(req_id).zfill(3)}"
    cert_url = request.host_url + f'certificate/req/{req_id}'
    return render_template('certificate.html',
        donation={'name':row['donor_name'],'blood_group':row['blood_group'],
                  'hospital':row['hospital'],'donation_date_fmt':row['donation_date_fmt'],
                  'donor_id':row['donor_id']},
        cert_id=cert_id, cert_url=cert_url)

# ---- RECORD DONATION (hospital) ----
def generate_cert_id(donor_id, donation_date):
    dd = str(donation_date)[:10].replace('-','')
    return f"BBAI-{dd[:4]}-{dd[4:8]}-{str(donor_id).zfill(3)}"

@app.route('/record-donation', methods=['GET','POST'])
@hospital_required
def record_donation():
    conn = get_db()
    cur = db_execute(conn, "SELECT * FROM hospitals WHERE id=?", (session['hospital_id'],))
    h = fetchone(cur)
    if request.method == 'POST':
        d = request.get_json() or request.form
        donor_id = int(d.get('donor_id'))
        cur = db_execute(conn, "SELECT * FROM donors WHERE id=?", (donor_id,))
        donor = fetchone(cur)
        if not donor: conn.close(); return jsonify({'success':False,'message':'Donor not found'}), 404
        donation_date = d.get('donation_date') or datetime.utcnow().strftime('%Y-%m-%d')
        db_execute(conn, "INSERT INTO donation_history (donor_id,hospital,donation_date,units_donated) VALUES (?,?,?,?)",
            (donor_id, h['name'], donation_date, float(d.get('units',1))))
        db_execute(conn, "UPDATE donors SET last_donation=? WHERE id=?", (donation_date, donor_id))
        conn.commit()
        cur = db_execute(conn, "SELECT id FROM donation_history WHERE donor_id=? ORDER BY id DESC LIMIT 1", (donor_id,))
        donation_id = fetchone(cur)['id']
        conn.close()
        return jsonify({'success':True,'message':'Donation recorded!','certificate_url':f'/certificate/{donation_id}'})
    query = request.args.get('q','')
    donors = []
    if query:
        cur = db_execute(conn, "SELECT * FROM donors WHERE name LIKE ? OR phone LIKE ? OR blood_group LIKE ? LIMIT 20",
            (f'%{query}%',f'%{query}%',f'%{query}%'))
        donors = fetchall(cur)
    conn.close()
    return render_template('record_donation.html', hospital=h, donors=donors, query=query)

@app.route('/certificate/<int:donation_id>')
def certificate(donation_id):
    conn = get_db()
    cur = db_execute(conn, """SELECT dh.*, d.name, d.blood_group, d.city, d.phone, d.email
        FROM donation_history dh JOIN donors d ON dh.donor_id=d.id WHERE dh.id=?""", (donation_id,))
    row = fetchone(cur)
    if not row: conn.close(); return "Not found", 404
    conn.close()
    dd = row['donation_date']
    try: row['donation_date_fmt'] = dd.strftime('%d %B %Y') if hasattr(dd,'strftime') else datetime.strptime(str(dd)[:10],'%Y-%m-%d').strftime('%d %B %Y')
    except: row['donation_date_fmt'] = str(dd)
    cert_id = generate_cert_id(row['donor_id'], row['donation_date'])
    cert_url = request.host_url + f'certificate/{donation_id}'
    return render_template('certificate.html', donation=row, cert_id=cert_id, cert_url=cert_url)

# ---- API ----
@app.route('/api/blood-compatibility/<blood_group>')
def api_blood_compat(blood_group):
    return jsonify({'blood_group':blood_group,'compatible':compatible_for_patient(blood_group)})

@app.route('/api/donor-eligibility', methods=['POST'])
def api_eligibility():
    d = request.get_json()
    el, reasons = check_eligibility(int(d.get('age',0)), float(d.get('weight',50)), d.get('last_donation'))
    return jsonify({'eligible':el,'reasons':reasons})


# ---- CHECK CERTIFICATE STATUS ----
@app.route('/check-certificate')
def check_certificate():
    phone = request.args.get('phone', '').strip()
    if not phone:
        return render_template('check_certificate.html')
    conn = get_db()
    cur = db_execute(conn, """
        SELECT id, donor_name, blood_group, hospital, donation_date,
               status, admin_note, requested_at
        FROM certificate_requests
        WHERE donor_id IN (SELECT id FROM donors WHERE phone=?)
           OR donor_name IN (SELECT name FROM donors WHERE phone=?)
        ORDER BY requested_at DESC
    """, (phone, phone))
    rows = fetchall(cur)
    conn.close()
    if not rows:
        return jsonify({'found': False})
    results = []
    for r in rows:
        dd = r['donation_date']
        try:
            date_fmt = dd.strftime('%d %b %Y') if hasattr(dd,'strftime') else datetime.strptime(str(dd)[:10],'%Y-%m-%d').strftime('%d %b %Y')
        except:
            date_fmt = str(dd)[:10]
        ra = r['requested_at']
        try:
            ra_fmt = ra.strftime('%d %b %Y, %I:%M %p') if hasattr(ra,'strftime') else str(ra)[:16]
        except:
            ra_fmt = str(ra)[:16]
        results.append({
            'id':           r['id'],
            'donor_name':   r['donor_name'],
            'blood_group':  r['blood_group'],
            'hospital':     r['hospital'],
            'donation_date':date_fmt,
            'status':       r['status'],
            'admin_note':   r['admin_note'] or '',
            'requested_at': ra_fmt
        })
    return jsonify({'found': True, 'requests': results})

# ---- ERRORS ----
@app.errorhandler(404)
def not_found(e): return render_template('404.html'), 404
@app.errorhandler(500)
def server_error(e): return render_template('500.html'), 500

# ---- STARTUP ----
init_db()

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=5000)
