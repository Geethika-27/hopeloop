# Smart Resource Allocation Prototype

A fully working FastAPI prototype for **data-driven volunteer coordination**.

It helps NGOs and social groups:
- ingest scattered community reports,
- convert reports into structured urgent needs,
- auto-create operational tasks,
- run intelligent volunteer-task matching using skills, urgency, and location,
- use Google Gemini for AI analysis,
- visualize ward pressure with an interactive map,
- provide role-based dashboards (coordinator, field ops, volunteer),
- queue and dispatch WhatsApp/SMS alerts,
- forecast category demand using historical and seasonal patterns.

## 1) Project Structure

```
smart-volunteer-prototype/
  app/
    main.py
    db.py
    models.py
    schemas.py
    matcher.py
    gemini.py
    templates/index.html
    static/styles.css
    static/app.js
  requirements.txt
  Dockerfile
  .dockerignore
  .env.example
```

## 2) Run Locally

1. Create and activate a virtual environment.

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

2. Install dependencies:

```powershell
pip install -r requirements.txt
```

3. Set Gemini before starting the app:

Copy `.env.example` to `.env`, then put your own key in the new file:

```powershell
copy .env.example .env
```

Then edit `.env` and set:

```powershell
$env:GEMINI_API_KEY="your_api_key"
$env:GEMINI_MODEL="gemini-2.0-flash"
```

The app will not start without `GEMINI_API_KEY`.

4. Start app:

```powershell
uvicorn app.main:app --reload
```

5. Open:
- UI: http://127.0.0.1:8000
- API docs: http://127.0.0.1:8000/docs

## 3) Key API Endpoints

- `POST /api/reports` - Ingest community report and generate need + task
- `POST /api/volunteers` - Register volunteer with skills
- `POST /api/allocate` - Run matching engine
- `GET /api/dashboard` - Metrics + urgent needs + critical tasks
- `GET /api/dashboard/role?role=coordinator|field|volunteer` - Role-based cards and priorities
- `GET /api/map/heat` - Ward heat map points with pressure and staffing gap
- `GET /api/forecast` - Demand projection by category with trend insights
- `POST /api/alerts` - Queue WhatsApp/SMS alerts
- `POST /api/alerts/dispatch` - Dispatch queued alerts (simulated provider)
- `GET /api/alerts` - Alert history and statuses
- `POST /api/demo/seed` - Seed demo volunteers

## 4) Matching Logic (Efficient & Practical)

Assignment score is weighted by:
- Skill overlap: 45%
- Location affinity: 20%
- Availability: 20%
- Task urgency: 15%

The allocation engine:
- fills tasks by priority,
- avoids duplicate task-volunteer assignments,
- caps active assignments per volunteer,
- marks tasks `in_progress` when staffing target is reached.

## 5) Deploy on Google Cloud Run

### Prerequisites
- Google Cloud account
- Billing enabled
- `gcloud` CLI installed
- Artifact Registry + Cloud Run APIs enabled

### Deploy steps

1. Login and set project:

```bash
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
```

2. Enable APIs:

```bash
gcloud services enable run.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com
```

3. Build and deploy from project folder:

```bash
gcloud builds submit --tag gcr.io/YOUR_PROJECT_ID/smart-volunteer-prototype
gcloud run deploy smart-volunteer-prototype \
  --image gcr.io/YOUR_PROJECT_ID/smart-volunteer-prototype \
  --platform managed \
  --region asia-south1 \
  --allow-unauthenticated
```

4. Set Gemini key on Cloud Run service before sending traffic:

```bash
gcloud run services update smart-volunteer-prototype \
  --region asia-south1 \
  --set-env-vars GEMINI_API_KEY=YOUR_KEY,GEMINI_MODEL=gemini-2.0-flash
```

## 6) Next Upgrades

- Add OCR pipeline for scanned paper survey ingestion.
- Add geospatial routing and travel-time scoring.
- Add real provider integrations (Twilio/Meta WhatsApp Cloud API) for production alert delivery.
- Integrate BigQuery + Looker Studio for city-scale analytics.
