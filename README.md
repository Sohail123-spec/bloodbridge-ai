# 🩸 BloodBridge AI
**Smart Blood Donation & Emergency Response Platform**

A startup-level web application connecting blood donors, patients, hospitals, and emergency responders through an intelligent centralized system.

---

## 🚀 Features
- Smart AI-powered donor matching with match scores
- Emergency request broadcasting with live board
- Blood compatibility engine (all 8 blood types)
- Hospital portal with Excel bulk donor upload
- Analytics dashboard with Chart.js
- Admin panel for platform management
- Eligibility checker (age, weight, last donation)
- Duplicate detection (phone + email)
- Donor profiles with donation history
- Email alerts to compatible donors
- Glassmorphism UI — startup-grade design
- Fully mobile responsive

---

## 🛠️ Local Setup

### 1. Clone / Download
```bash
cd bloodbridge-ai
```

### 2. Create Virtual Environment
```bash
python -m venv venv
source venv/bin/activate      # Mac/Linux
venv\Scripts\activate         # Windows
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure Environment
```bash
cp .env.example .env
# Edit .env with your values
```

### 5. Run
```bash
python app.py
```
Visit: **http://localhost:5000**

---

## 🔐 Default Credentials

| Role  | Email | Password |
|-------|-------|----------|
| Admin | admin@bloodbridge.ai | admin123 |

---

## 📁 Excel Upload Format

Hospitals can upload `.xlsx` files with these columns:

| name | blood_group | city | phone | last_donation | available |
|------|-------------|------|-------|---------------|-----------|
| John | O+ | Hyderabad | 9876543210 | 2024-01-15 | Yes |

Optional columns: `age`, `gender`, `email`, `weight`

---

## 🌐 Deploy on Render

1. Push code to GitHub
2. Go to [render.com](https://render.com) → New Web Service
3. Connect your GitHub repo
4. Set environment variables:
   - `SECRET_KEY` → any random string
   - `DATABASE_URL` → your PostgreSQL URL (or leave as SQLite)
5. Build: `pip install -r requirements.txt`
6. Start: `gunicorn app:app`
7. Deploy!

---

## 📊 Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python, Flask, SQLAlchemy |
| Frontend | HTML5, CSS3, Bootstrap 5, Chart.js |
| Database | SQLite (dev) / PostgreSQL (prod) |
| Data Processing | Pandas, OpenPyXL |
| Email | Flask-Mail |
| Deployment | Render + Gunicorn |

---

## 📱 Pages

| URL | Description |
|-----|-------------|
| `/` | Landing page with hero, stats, emergency board |
| `/register-donor` | 3-step donor registration |
| `/search-donor` | AI-powered donor search |
| `/emergency-request` | Post emergency request |
| `/emergency-board` | Live emergency board |
| `/analytics` | Analytics dashboard |
| `/hospital-login` | Hospital portal login |
| `/hospital-dashboard` | Hospital management |
| `/hospital-upload` | Excel bulk upload |
| `/admin-login` | Admin panel access |
| `/admin-dashboard` | Admin overview |

---

## 👨‍💻 Built With BloodBridge AI
*Saving lives through intelligent technology.*
