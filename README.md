# RFP BidOS

Local-first Python, FastAPI, and React dashboard skeleton for RFP bid workflows.

## Backend Setup

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
python -m app.cli init-db
python -m app.cli score-opportunity 1
python -m app.cli score-all-opportunities
uvicorn app.main:app --reload
```

## Frontend Setup

```powershell
cd frontend
npm install
npm run dev
```

## Run Commands

Backend:

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload
```

Scoring:

```powershell
python -m app.cli score-opportunity 1
python -m app.cli score-all-opportunities
```

Frontend:

```powershell
cd frontend
npm.cmd install
npm.cmd run dev
```

## Warning

Do not commit `.env`, `data/sessions`, `.venv`, or `node_modules`.
