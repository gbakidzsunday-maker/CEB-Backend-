# Secure Real-Time CBE System — Backend

FastAPI backend for the security-enhanced Computer-Based Examination system
(Chapters 1–3 design), using SQLite so it deploys as a single Docker
container with no external database service required.

## What's implemented

- **Auth**: candidate + admin registration/login, Argon2 password hashing,
  JWT session tokens, account lockout after repeated failed logins.
- **Levels, courses, and auto-distribution**: a candidate selects an
  academic `level` at registration:
  - `ND1`, `ND2` — National Diploma, no departmental split.
  - `HND1_SWD`, `HND1_NCC`, `HND2_SWD`, `HND2_NCC` — Higher National
    Diploma, split by option (SWD = Software Engineering, NCC = Network
    and Computer Connectivity/Communication) as well as by year.
  An admin creates `Course`s, each tagged with one of these levels.
  Enrollment is fully automatic in both directions:
  - Creating a course auto-enrolls every existing candidate at that level.
  - Registering a candidate auto-enrolls them in every existing course at
    their level.
  No manual "assign student to course" step exists or is needed.
- **Exam management**: admin-only CRUD for exams and questions; every exam
  belongs to a course (`course_id`), and inherits that course's `level`.
  Candidates only ever see, or can interact with, exams for courses they're
  enrolled in — enforced server-side on every relevant endpoint, not just
  in the exam list. correct_option` is never sent to candidates.
- **Real-time response capture**: each answer is persisted immediately
  (insert-or-update) with a SHA-256 checksum over its contents.
- **Scoring**: `/exams/{id}/submit` scores stored responses and writes a
  `Result` row, also checksummed.
- **Security layer**: parameterised ORM queries (no raw SQL → no SQL
  injection surface), per-IP/per-endpoint rate limiting (mitigates
  brute-force and flood/DoS traffic), an append-only `SecurityLog` audit
  trail, and `/security/verify/...` endpoints that recompute a record's
  checksum to detect direct database tampering.
- **Tests**: 21 pytest tests covering auth, access control, the full
  exam→response→score flow, rate limiting, account lockout, a SQL-injection
  -style login payload, and two tamper-detection scenarios (see
  `tests/test_security.py`).

## Project layout

```
app/
  main.py              FastAPI app + router registration
  config.py            Settings (env-var driven)
  database.py          SQLAlchemy engine/session (SQLite)
  models.py            ORM models: Candidate, Administrator, Examination,
                        Question, Response, Result, SecurityLog
  schemas.py            Pydantic request/response models
  security.py           Argon2 hashing, JWT, checksum helper
  rate_limit.py          In-memory sliding-window rate limiter
  deps.py                Auth guards, current-user resolution, security-log writer
  enrollment.py          Auto-distribution helpers (course<->candidate by level)
  routers/
    auth.py               /auth/...
    courses.py             /courses/...
    exams.py               /exams/...
    responses.py            /exams/{id}/responses, /exams/{id}/submit, /results/me
    security_monitor.py      /security/logs, /security/verify/...
tests/                    pytest suite (in-memory SQLite, fully isolated)
Dockerfile
render.yaml               Optional Render "infra as code" blueprint
```

## Run locally

```bash
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env              # then edit SECRET_KEY

uvicorn app.main:app --reload
```

Visit `http://127.0.0.1:8000/docs` for interactive Swagger docs.

## Run the tests

```bash
pytest -v
```

All 30 tests should pass. Tests run against an isolated in-memory SQLite
database per test — they never touch your real `data/cbe.db`.

## Run with Docker (locally, before deploying)

```bash
docker build -t cbe-backend .
docker run -p 8000:8000 -e SECRET_KEY=dev-secret cbe-backend
```

Then `curl http://localhost:8000/health` should return `{"status":"healthy"}`.

## Deploy to Render

**Option A — Dashboard, no render.yaml:**
1. Push this folder to a GitHub repo.
2. Render → New → Web Service → connect the repo.
3. Runtime: **Docker**. Render will detect the `Dockerfile` automatically.
4. Add an environment variable `SECRET_KEY` with a long random value
   (Render can generate one for you).
5. (Optional but recommended) Add a **Persistent Disk**, mount path
   `/app/data`, so your SQLite file survives restarts/redeploys. Without
   it, data resets on every deploy — fine for a demo, not for a real exam.
6. Deploy. Render assigns `$PORT` automatically; the Dockerfile already
   reads it.

**Option B — render.yaml (Blueprint):**
Push the repo, then in Render choose **New → Blueprint** and point it at
the repo. `render.yaml` already declares the service, the generated
`SECRET_KEY`, and a 1GB persistent disk mounted at `/app/data`.

## Levels, courses, and auto-distribution — new endpoints

| Method | Path | Auth | Body | Notes |
|---|---|---|---|---|
| POST | `/courses` | Admin | `{name, code, level}` | `level` is one of `ND1`, `ND2`, `HND1_SWD`, `HND1_NCC`, `HND2_SWD`, `HND2_NCC` (see `app/models.py::Level` — edit this enum if Mapoly's actual level/option names differ, e.g. if NCC stands for something else at your school). Auto-enrolls every existing candidate at that exact level; response includes `enrolled_candidates` count. |
| GET | `/courses` | Admin | — | Optional `?level=ND1` filter. |
| GET | `/courses/mine` | Candidate | — | Courses the caller has been auto-enrolled in. |
| POST | `/exams` | Admin | now requires `course_id` | The exam's `level` is copied from the course at creation time. |
| GET | `/exams` | Candidate or Admin | — | **Now requires auth** (previously public). Admins see all active exams; candidates only see exams belonging to a course they're enrolled in. |
| GET/POST | `/exams/{id}/...` | Candidate | — | Every candidate-facing exam endpoint (`questions`, `responses`, `submit`) now checks enrollment server-side and returns `403` if the candidate isn't enrolled in that exam's course — this isn't just a UI-level filter. |

**Schema change — you need a fresh database file.** This update adds a
`level` column to `candidates`, a `course_id`/`level` column to
`examinations`, and two new tables (`courses`, `course_enrollments`). Since
this project uses `Base.metadata.create_all()` rather than Alembic
migrations, it can only *create* new tables — it won't add columns to
tables that already exist. If you have an existing `data/cbe.db` from
before this change, delete it (or point `DATABASE_URL` at a new file)
before redeploying, or existing rows will be missing the new columns.

## A note on SQLite in production

SQLite is fine for a prototype/dissertation demo and for the load levels
you'll generate in your attack-simulation tests. It is **not** a good fit
for multiple concurrent Render instances (SQLite is single-writer,
single-file) — keep the Render service scaled to **one instance**. If you
later need multi-instance scaling, swap `DATABASE_URL` for a Postgres
connection string; the SQLAlchemy models don't need to change.

## Suggested attack-simulation targets (for Chapter 4)

- **SQL injection**: fire classic payloads (`' OR '1'='1`, etc.) at
  `/auth/candidate/login` — `test_sql_injection_style_payload_does_not_authenticate`
  already demonstrates the app is unaffected because SQLAlchemy's ORM
  parameterises every query.
- **Brute force / DoS**: hammer `/auth/candidate/login` or
  `/exams/{id}/responses` — the rate limiter returns `429` and logs a
  `rate_limit_exceeded` `SecurityLog` event once the threshold is crossed.
- **Session/token tampering**: try reusing an expired or hand-edited JWT
  against a protected endpoint — `get_current_payload` rejects it with 401.
- **Data tampering**: edit a `Response`/`Result` row directly in the
  SQLite file, then call `/security/verify/response/{id}` — `intact`
  flips to `false`.

Log the pass/fail and response-time results from each of these against
this **secured** build vs. a deliberately stripped-down copy (remove the
rate limiter / checksum / Argon2 calls) to get the security-vs-baseline
comparison your Chapter 4 evaluation needs.
