from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import analysis, documents, opportunities, scraper, sources

app = FastAPI(title="RFP BidOS")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(opportunities.router)
app.include_router(documents.router)
app.include_router(scraper.router)
app.include_router(analysis.router)
app.include_router(sources.router)


@app.get("/")
def read_root() -> dict[str, str]:
    return {"app": "RFP BidOS"}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
