from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import Base, engine, SessionLocal
from app.routers import auth, exams, responses, security_monitor, courses, admin_students, parent_portal
from app.seed import seed_admin

# Create tables on startup. For a real production rollout you'd use
# Alembic migrations instead, but create_all is fine for this prototype.
Base.metadata.create_all(bind=engine)

# Auto-seed a default administrator account (no-op if one already
# exists, or if SEED_ADMIN=false). See app/seed.py for details.
_seed_db = SessionLocal()
try:
    seed_admin(_seed_db)
finally:
    _seed_db.close()

app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    description="Prototype secure real-time computer-based examination backend.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(courses.router)
app.include_router(exams.router)
app.include_router(responses.router)
app.include_router(security_monitor.router)
app.include_router(admin_students.router)
app.include_router(parent_portal.router)


@app.get("/", tags=["health"])
def root():
    return {"status": "ok", "service": settings.APP_NAME}


@app.get("/health", tags=["health"])
def health():
    return {"status": "healthy"}
