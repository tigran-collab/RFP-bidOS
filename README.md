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
uvicorn app.main:app --reload
```

Frontend:

```powershell
cd frontend
npm run dev
```

## Warning

Do not commit `.env`, `data/sessions`, `.venv`, or `node_modules`.
