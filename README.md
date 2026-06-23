# 🩸 BloodBridge AI
**Smart Blood Donation & Emergency Response Platform**

A full-stack web application connecting blood donors, patients, and hospitals through a centralized matching, emergency-broadcast, and verified-certificate system.

---

## 🚀 Features

- **Smart donor matching** — weighted 0–100 match score based on blood compatibility (40 pts), same city (30 pts), availability (20 pts), and eligibility (10 pts)
- **Blood compatibility engine** covering all 8 blood types
- **Emergency request broadcasting** with a live, auto-updating board
- **Hospital portal** — own login, dashboard, bulk donor import via Excel (`.xlsx`), and direct donation recording
- **Verified donation certificates** — issued instantly when a hospital records a donation, or after admin review when a donor self-submits proof
- **Donor eligibility checker** (age 18–65, weight ≥ 50kg, 56+ days since last donation)
- **Admin panel** — manage donors and emergency requests, review certificate requests, change password
- **Analytics dashboard** — blood group distribution, city coverage, monthly trends, urgency breakdown (Chart.js)
- **Duplicate detection** on donor phone number, both at registration and on bulk Excel upload
- **Custom dark UI** with a video background (homepage hero + blurred ambient loop on every other page), fully responsive

---

## 🛠️ Local Setup

### 1. Clone the repo
```bash
git clone https://github.com/your-username/bloodbridge-ai.git
cd bloodbridge-ai
```

### 2. Create a virtual environment
```bash
python -m venv venv
source venv/bin/activate      # Mac/Linux
venv\Scripts\activate         # Windows
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure environment
```bash
cp .env.example .env
# Edit .env with your own SECRET_KEY (DATABASE_URL can be left as-is for local SQLite)
```

### 5. Run
```bash
python app.py
```
Visit: **http://localhost:5000**

The local database is SQLite and is created automatically on first run — no setup needed.

---

## 🔐 Default Admin Credentials

| Role  | Email | Password |
|-------|-------|----------|
| Admin | admin@bloodbridge.ai | admin123 |

**Change this password immediately after first login** via Admin Dashboard → Change Password.

---

## 📁 Excel Upload Format (Hospital Portal)

Hospitals can bulk-import donors via `.xlsx`. The header row must be the very first row of the sheet — no title rows above it.

**Required columns:**

| name | blood_group | city | phone |
|------|-------------|------|-------|
| John | O+ | Hyderabad | 9876543210 |

**Optional columns:** `email`, `age`, `gender`, `weight`, `last_donation`, `available`

Rows with a phone number that already exists in the system are skipped as duplicates.

---

## 🌐 Deploy on Render

1. Push code to GitHub
2. Go to [render.com](https://render.com) → New → Web Service → connect your repo
3. Create a PostgreSQL instance on Render and copy its **Internal Database URL**
4. On the web service, set environment variables:
   - `SECRET_KEY` → any random string
   - `DATABASE_URL` → the PostgreSQL Internal URL from step 3
5. Build command: `pip install -r requirements.txt`
6. Start command: `gunicorn app:app`
7. Deploy

> ⚠️ Render's free tier has an ephemeral filesystem — without `DATABASE_URL` set to a real PostgreSQL instance, a local SQLite file will be wiped on every restart. The app auto-detects `DATABASE_URL` and switches from SQLite to PostgreSQL with no code changes required.

---

## 📊 Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3, Flask |
| Database | SQLite (local dev) / PostgreSQL (production) — raw SQL, no ORM |
| Data Processing | Pandas, OpenPyXL (Excel import) |
| Auth | Werkzeug password hashing, server-side sessions |
| Frontend | Jinja2, Bootstrap 5 (grid only), custom CSS design system |
| Charts | Chart.js |
| Deployment | Render + Gunicorn |

---

## 📱 Pages

| URL | Description |
|-----|-------------|
| `/` | Homepage — hero, live emergency ticker, quick actions |
| `/register-donor` | Multi-step donor registration |
| `/search-donor` | Smart donor search with AI match scoring |
| `/donor-detail/<id>` | Individual donor profile & eligibility |
| `/emergency-request` | Post an emergency blood request |
| `/emergency-board` | Live board of active emergency requests |
| `/hospital-register`, `/hospital-login` | Hospital account creation & login |
| `/hospital-dashboard` | Hospital's private dashboard |
| `/hospital-upload` | Bulk donor import via Excel |
| `/record-donation` | Hospital records a donation & issues a certificate |
| `/analytics` | Platform-wide analytics dashboard |
| `/admin-login`, `/admin-dashboard` | Admin login & control panel |
| `/admin-manage-donors`, `/admin-manage-requests` | Admin moderation tools |
| `/admin-certificate-requests` | Admin certificate review queue |
| `/request-certificate` | Donor self-submits a certificate request with proof photo |
| `/check-certificate` | Donor checks certificate status by phone number |
| `/certificate/<id>`, `/certificate/req/<id>` | Public certificate view/print page |

---

## 👨‍💻 Built With BloodBridge AI
*Saving lives through intelligent technology.*