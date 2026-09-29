# LearnHub

A learning management system built as a small SaaS app. Teachers publish courses,
upload lectures and notes, and build tests. Students watch, read, practise and sit
timed exams, with every score tracked.

FastAPI + SQLAlchemy on the back, server-rendered Jinja2 with vanilla JavaScript on
the front. No build step, no bundler, no npm — `uvicorn` is the only thing you run.

---

## Quick start

Requires **Python 3.10+** (the Docker image uses 3.12).

```bash
cd LMS

python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate

pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open <http://localhost:8000>. The database (`lms.db`) is created on first run,
along with three demo accounts, an **ECAT** track (Physics and Chemistry, each
split into chapters), a standalone sample course and a few live classes:

| Username  | Password     | Role    |
|-----------|--------------|---------|
| `teacher` | `teacher123` | Teacher |
| `student` | `student123` | Student |
| `admin`   | `admin123`   | Admin   |

There is nothing else to configure. Copy `.env.example` to `.env` only when you
want to change something.

---

## Features

### For everyone
- **Tracks** — exam programmes (ECAT, SAT, MDCAT) that group subjects. The
  hierarchy is **track → subject → chapter → videos, notes, practice tests and
  grand tests**. Join a track once and every subject inside it unlocks,
  including subjects added later.
- **Chapters** — each subject is split into units, and every piece of content is
  filed under one. A test with no chapter covers the whole subject; content with
  no chapter shows under *Unfiled* and still works.
- **Calendar** — a month grid of live classes, shared by both roles. Students see
  the courses they're enrolled in, teachers see the ones they own. Times are
  stored in UTC and rendered in each viewer's own timezone.
- **Live classes** — a built-in video room (no accounts, embedded in the app) or
  a teacher's own Zoom / Meet / Teams link. The room unlocks 10 minutes before
  the start and the waiting page opens itself when it does.

### Feedback
- **Students rate the subjects they took** — 1–5 stars with an optional comment.
  One review per student per subject, edited in place rather than stacked.
- **Averages surface everywhere** — catalogue cards, track pages, and a full
  breakdown with a star distribution on the subject page.
- **Teachers get a feedback page** collecting every review across their
  subjects, with an overall rating and a per-subject breakdown.
- **Moderation hides, it never edits.** A teacher can unpublish a review that is
  abusive or off-topic; there is deliberately no way to change its text. A
  hidden review disappears for other students and stops counting towards the
  average, while its author still sees it, marked as hidden.

### Subscriptions
- **Per-track plans.** Each track carries its own plans — *Monthly*, *Annual*,
  whatever you name them — with a price, currency and length in days.
- **Payment happens outside the app.** A student picks a plan and sends a
  request; an admin records the payment (bank transfer, JazzCash, EasyPaisa,
  cash) against a reference and the subscription activates. Nothing is charged
  here and no gateway is involved.
- **Tracks are free until you say otherwise.** `requires_subscription` is off by
  default, so adding billing never paywalled anything that already existed.
  Turn it on per track in the track's settings.
- **Admins can** confirm, reject, extend, cancel, or **grant** free access
  outright for scholarships and trials.

### For students
- **Course catalogue** with search and subject filtering, and one-click enrollment.
- **Video player** that remembers where you stopped, resumes there next time, and
  marks a lecture complete at 90% watched. Auto-advances to the next lecture.
- **Notes and handouts** — PDFs, slides, worksheets — downloadable per lecture or
  per course.
- **Practice tests**: untimed, unlimited retries, and every answer is checked the
  moment you pick it, with an explanation.
- **Grand tests**: timed, normally one attempt, optional negative marking, answers
  hidden until you submit.
- **Test runner** with a question palette, flag-for-review, a countdown that shifts
  amber then red, keyboard shortcuts, and autosave that survives a refresh.
- **Results** — a per-question review of what you got wrong and why, plus a score
  history and trend.

### For teachers
- **Studio** showing every course, enrollment counts and the class average.
- **Lectures** by upload (MP4/WebM/MOV, streamed to disk with a live progress bar)
  or by pasting a YouTube / Vimeo / direct link, which is normalised to an embed.
- **Notes** by drag-and-drop, attached to a lecture or to the whole course.
- **Track builder** — create a programme, file your own courses into it as
  subjects, then break each subject into chapters and drag its videos, notes and
  tests into them from a dropdown.
- **Scheduling** a live class from the calendar: pick a course, a start time and
  a length, and either take the built-in room or paste your own meeting link.
  Classes can be cancelled (students keep seeing it, struck through) or deleted.
- **Test builder** with four question types, inline reordering, duplication, live
  mark totals, and Ctrl+S to save.
- **Results** per test — every submission, the class average and pass rate, plus a
  hardest-questions breakdown showing which question the class actually failed.
- **Students** view with each learner's lecture progress and test average.

### For admins
- **Overview** — every number on the site in one page: people by role, tracks,
  subjects, videos, tests, live classes, submissions and the site-wide average,
  plus every track and course with its owner.
- **People** — add students, teachers and admins; search and filter by role or
  status; rename, change role, deactivate, reset a password, delete.
- **Deactivate vs delete.** A deactivated account keeps all its data and simply
  cannot sign in. Deleting is only offered when it is safe (see below).
- **Reassign** — move a teacher's courses, tracks and classes to another teacher
  in one action, which is what makes their account safe to remove.
- Admins manage every track and course regardless of who owns it.

### Question types
`single` (one correct option) · `multi` (all-correct-none-wrong) · `truefalse` ·
`numeric` (a typed number within a tolerance).

---

## Project structure

```
LMS/
├── app/
│   ├── main.py             app factory, static mount, error pages, startup
│   ├── config.py           pydantic-settings, reads .env
│   ├── database.py         SQLite by default, Postgres when DATABASE_URL is set
│   ├── templating.py       shared Jinja2 env + asset_url() cache-busting
│   ├── models/             user, track, course, content, assessment, schedule,
│   │                       billing, feedback
│   ├── schemas/            pydantic request/response shapes
│   ├── services/           auth, admin, billing, feedback, track, chapter,
│   │                       course, content, assessment, grading, schedule,
│   │                       storage, migrate, seed
│   ├── routers/            auth, admin, billing, dashboard, tracks, courses,
│   │                       learn, tests, teach, calendar, files
│   ├── static/
│   │   ├── css/style.css   the whole design system, token-driven
│   │   └── js/             app, player, quiz, upload, builder, calendar,
│   │                       classroom
│   └── templates/          base, auth, student pages, teach/, admin/, errors/
├── uploads/                videos/ and notes/ — gitignored, served behind auth
├── Dockerfile              container image (binds to $PORT)
├── render.yaml             Render blueprint: web service + Postgres
├── requirements.txt
└── .env.example
```

Layering is strict: `routers/` handle HTTP only, `services/` hold the logic and
never import FastAPI, `models/` are SQLAlchemy, `schemas/` are pydantic.

---

## Key endpoints

### Pages
| Route | Who | What |
|---|---|---|
| `/login` `/register` `/logout` | anyone | Session auth |
| `/dashboard` | student | Continue watching, courses, due tests, trend |
| `/courses` `/courses/{slug}` | any | Catalogue and course detail |
| `/learn/{lecture_id}` | enrolled | The player |
| `/admin` `/admin/users` | admin | Site overview and people management |
| `/admin/subscriptions` | admin | Confirm payments, extend, cancel, grant |
| `/subscriptions` | student | Your plans, and what else is available |
| `/teach/feedback` | teacher | Every review across your subjects |
| `/tracks` `/tracks/{slug}` | any | Programme catalogue and one track's syllabus |
| `/teach/tracks/{id}` | owner | Track builder — settings and subjects |
| `/calendar` | any | Month grid of live classes |
| `/classes/{id}` | enrolled | The live classroom |
| `/tests?kind=practice\|grand` | student | Available tests |
| `/attempts/{id}` | owner | The test runner |
| `/attempts/{id}/result` | owner | Score and answer review |
| `/results` | student | Score history |
| `/teach` | teacher | Studio |
| `/teach/courses/{id}` | owner | Lectures, notes and tests |
| `/teach/tests/{id}/edit` | owner | Test builder |
| `/teach/tests/{id}/results` | owner | Submissions and difficulty |

### JSON
| Method | Route | What |
|---|---|---|
| `POST` | `/courses/{id}/enroll` · `/unenroll` | Enrollment |
| `POST` | `/learn/api/{id}/progress` · `/complete` | Watch progress |
| `PUT/DELETE` | `/courses/{id}/review` | Leave, update or remove your review |
| `POST` | `/teach/api/reviews/{id}/moderate` | Hide or restore a review |
| `POST` | `/subscriptions/request` | Ask for a plan (lands as pending) |
| `POST` | `/admin/api/subscriptions/{id}/approve` · `/reject` · `/cancel` · `/extend` | Subscription lifecycle |
| `POST` | `/admin/api/subscriptions/grant` | Free access, no payment |
| `POST/PUT/DELETE` | `/teach/api/tracks/{id}/plans` · `/teach/api/plans/{id}` | Pricing |
| `POST/PUT/DELETE` | `/admin/api/users/...` | Accounts, roles and status |
| `POST` | `/admin/api/users/{id}/password` · `/reassign` | Reset a password; hand over content |
| `POST` | `/tracks/{id}/join` · `/leave` | Track membership |
| `POST/PUT/DELETE` | `/teach/api/tracks/...` | Tracks and their subjects |
| `POST/PUT/DELETE` | `/teach/api/chapters/...` | Chapter CRUD |
| `POST` | `/teach/api/courses/{id}/chapters/assign` | File content under a chapter |
| `GET` | `/calendar/api/events?start=&end=` | Classes visible to the caller |
| `GET` | `/classes/{id}/status` | Has the room opened yet? |
| `POST/PUT/DELETE` | `/teach/api/classes/...` | Schedule, edit, cancel, delete |
| `POST` | `/api/attempts/{id}/answer/{qid}` | Autosave one answer |
| `POST` | `/api/attempts/{id}/check/{qid}` | Practice feedback (403 on grand tests) |
| `POST` | `/api/attempts/{id}/submit` | Submit and score |
| `POST/PUT/DELETE` | `/teach/api/...` | Course, lecture, note and test CRUD |
| `GET` | `/files/video/{id}` · `/files/note/{id}` | Authenticated media |

Interactive API docs are at `/docs`.

---

## Design notes

**The clock is server-side.** `Attempt.expires_at` is stamped when the attempt
begins and re-checked on every request. The countdown in the browser is display
only — editing the page's JavaScript cannot buy extra time, and closing the tab
does not pause anything. An attempt found past its deadline is auto-submitted and
scored from whatever was saved.

**The answer key never reaches an open attempt.** The payload handed to the test
runner is built by hand rather than serialised from the ORM, precisely so it is
obvious that `is_correct`, `explanation` and `numeric_answer` are absent. Practice
feedback comes from a separate endpoint that marks one question server-side; that
endpoint refuses grand tests outright.

**Uploads live outside `/static`.** A `StaticFiles` mount performs no
authorisation, so anything under it is readable by anyone who can guess the URL.
Course media is served instead by `routers/files.py` behind an enrollment check.
Stored filenames are UUIDs; the teacher's original name is reattached in the
`Content-Disposition` header on download.

**Two roles, checked twice.** Being a teacher does not make someone a teacher *of
this course* — every write re-checks `course.teacher_id` in the service layer,
not just the role in the router.

**Moderation hides, it never edits.** A teacher can unpublish a review but there
is deliberately no endpoint that changes its text — a teacher who could rewrite
what a student said would make every rating on the site worthless. Unpublishing
is a real removal, not a cosmetic one: averages are computed over published rows
only, so a hidden review stops counting rather than leaving a ghost in the score.
The author still sees their own, marked as hidden, because silently vanishing
someone's words is its own kind of dishonesty.

**Entitlement is a question about time, not a status column.** A subscription
that lapsed overnight still reads `active` until something notices, so every
access check goes through `is_current` — status *and* window — rather than the
status alone. The background sweep that flips lapsed rows to `expired` is purely
cosmetic; nothing depends on it having run, because the thing that notices an
expiry must never be the access check waving it through.

**Money is stored as integers.** Minor units (paisa, cents), never floats. The
form takes rupees and multiplies by 100 on the way in. Rs 2,500.00 held as a
float becomes 2499.9999999999995 sooner or later, and prices are the last place
that should be approximate.

**What was agreed is copied, not referenced.** A subscription snapshots its
price, currency and plan name at request time. Repricing a plan next term cannot
rewrite what somebody already paid, and withdrawing a plan leaves every receipt
sold on it still meaningful. For the same reason a track that has ever been
subscribed to cannot be deleted at all — unpublish it instead.

**Deleting a teacher would delete their teaching.** `User.courses_taught`
cascades with delete-orphan, so `db.delete(teacher)` takes their courses — and
each course takes its chapters, lectures, notes, tests and every *other*
student's attempts. Far too much collateral for one click, so `delete_user`
refuses while a teacher owns anything and names what is in the way. The UI turns
that 409 into the fix rather than a wall: it offers to reassign their content to
another teacher, after which deletion is genuinely safe. Deleting a student does
go ahead, and sweeps up the rows that hang off them by foreign key without a
cascading relationship (`TrackEnrollment`, `LectureProgress`) — orphans pointing
at a vanished id are worse than the delete itself.

**An admin must not be able to lock everyone out.** Deleting yourself, changing
your own role, deactivating yourself, or removing the last active administrator
are refused outright rather than confirmed. A confirmation dialog is no help
once the door has already shut. The account form disables the role and status
fields on your own row, so the refusal is visible before the click, not after.

**A subject is a course, not a new thing.** Tracks were added by hanging a
nullable `track_id` off `Course` rather than building a parallel hierarchy. A
course in a track is a *subject*; a course with no track behaves exactly as it
always did. That one nullable column is why the existing catalogue, every
`/courses/{slug}` URL, enrollment, the player and the test builder all kept
working untouched — and why a subject can be pulled out of a track without its
content moving anywhere.

**Two ways in, one answer.** Access can come from enrolling in a course or from
joining its track, so `has_access()` is the single place that asks. `is_enrolled`
stays narrow — direct enrollment only — because that is what the Enroll/Leave
button acts on, and a track member has nothing there to leave. Membership is
stored once against the track rather than fanned out into per-course rows, so a
subject added next term is unlocked for existing members with no backfill.

**Deleting a grouping never deletes the teaching.** Removing a chapter unfiles
its lectures, notes and tests; deleting a track detaches its subjects. Both
report what they moved. Reorganising a syllabus is routine and must never be a
way to lose a term's work by mis-clicking.

**A meeting room is a bearer token.** The built-in classroom is a public Jitsi
room, so anyone who learns the room name can walk in. Room names are therefore
random rather than derived from the course, and `to_payload` omits the URL
entirely unless the caller may join *right now* — an upcoming class never puts
its room name in the page source. The join window is server-side for the same
reason the exam clock is: a student whose device clock is fast must not get in
early, so the waiting page asks the server rather than trusting `Date.now()`.

**Every instant is UTC on the wire.** The database stores UTC, the API speaks
ISO-8601 with an offset, and the browser does the formatting. A teacher in
Karachi scheduling 15:00 and a student in London seeing 11:00 are looking at one
stored value. `starts_at` without a timezone is rejected rather than guessed at.

**Colour lives in one file.** `style.css` defines every colour as a token and
templates never hardcode one. Re-theming the app means editing the `:root` block.

**Tests lock after submission.** Editing questions once students have sat a test
would silently invalidate their marks, so the builder refuses with a 409.

---

## Configuration

Everything is optional; see `.env.example` for the full list.

| Variable | Default | Notes |
|---|---|---|
| `DATABASE_URL` | SQLite `./lms.db` | Set a `postgresql://` URL to switch; the psycopg3 driver is applied automatically |
| `APP_NAME` | `LearnHub` | Shown in the page titles and header |
| `DEBUG` | `true` | Set `false` in production |
| `SECRET_KEY` | dev placeholder | **Change this in production** |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `720` | Session length |
| `UPLOAD_DIR` | `./uploads` | Where media is written |
| `MAX_VIDEO_MB` / `MAX_NOTE_MB` | `512` / `32` | Enforced while streaming, not after |
| `DEFAULT_PASS_PERCENT` | `40` | Pass mark for new tests |
| `GRAND_TEST_DEFAULT_MINUTES` | `60` | Default duration of a grand test |
| `LECTURE_COMPLETE_RATIO` | `0.9` | Watched fraction that counts as complete |
| `MEET_DOMAIN` | `meet.jit.si` | Jitsi instance for built-in rooms; point at a self-hosted one to keep traffic in-house |
| `CLASS_JOIN_LEAD_MINUTES` | `10` | How early students may enter a room |
| `SHOW_DEMO_CREDENTIALS` | `false` | Print the demo logins on the sign-in page. Local demos only |
| `SEED_DEMO_DATA` | `true` | **Set to `false` before deploying** |

### Switching to PostgreSQL

```bash
createdb lms_db
# .env
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/lms_db
```

Tables are created at startup via `Base.metadata.create_all`. There are no
migrations — see the limitations below.

---

## Notes and limitations

- **No real migrations.** `services/migrate.py` adds *nullable* columns an older
  database is missing, which covers hanging a new optional relationship off an
  existing table (that is how `track_id` and `chapter_id` shipped without anyone
  dropping their data). Anything needing a backfill, a type change or a `NOT
  NULL` constraint is a genuine migration — add Alembic before this holds data
  anyone cares about.
- **Local disk storage.** Uploads go to the server's filesystem, so the app does
  not scale horizontally as-is. S3 or similar would be the next step.
- **YouTube and Vimeo lectures have no automatic progress.** A cross-origin iframe
  won't report `currentTime` without loading each provider's SDK, so those
  lectures rely on the "Mark as complete" button. Uploaded and direct-link videos
  are tracked properly.
- **Multi-select is all-or-nothing.** No partial credit for getting three of four
  options right.
- **Built-in classes run on a public Jitsi instance.** `meet.jit.si` is free and
  needs no account, but it is someone else's server and its rooms have no
  password — the only thing protecting a class is that the room name is random
  and the app hands it out solely to enrolled users inside the join window. For
  anything confidential, self-host Jitsi and set `MEET_DOMAIN`.
- **Live classes are not recorded, and attendance is not tracked.** Who actually
  turned up is not written back to the database.
- **No calendar export.** No iCal feed or Google Calendar sync, so classes live
  only in this app.
- **No email, so password resets are manual.** A user who forgets their password
  needs an admin to set a new one and tell them what it is. There is no
  self-service reset, no verification and no notifications.
- **No audit log.** Nothing records which admin created, changed or deleted an
  account. Worth adding before more than one person has the role.
- **No payment gateway.** Money is collected outside the app and recorded by
  hand, so the numbers are only as good as the person entering them. There is no
  card capture, no reconciliation against a bank feed and no refund handling —
  cancelling stops access and leaves the payment record alone.
- **No renewal reminders and no auto-renew.** A subscription simply lapses on
  its end date; nobody is emailed beforehand and nothing recurs. Students see
  the days remaining on `/subscriptions`; an admin extends when payment arrives.
- **No invoices or receipts.** Nothing generates a PDF or a numbered invoice.
- **Reviews are not verified against progress.** Anyone with access to a subject
  can rate it, including someone who watched nothing. Gating on a completion
  threshold would be the next step.
- **No replies to reviews.** A teacher can hide one but cannot answer it
  publicly, and nothing notifies them when a new review lands.
- **Rate limiting is absent.** Login has no lockout or throttle.
- **The video player is the browser's.** No adaptive bitrate, no transcoding — a
  400 MB MP4 is served as a 400 MB MP4 (with range requests, so seeking works).

## Deploying

A tunnel (ngrok, cloudflared) is fine for showing someone the app for an hour.
It is not hosting: the URL changes on every restart and the link dies with the
laptop. For a permanent address, deploy the container.

`Dockerfile` and `render.yaml` are in the repo. On Render: push to GitHub, then
**New → Blueprint → pick the repo**. It reads `render.yaml` and creates the web
service plus a Postgres database. The same image runs on Railway, Fly.io, Cloud
Run or any VPS — `$PORT` is honoured, which is all those platforms require.

**Use Postgres, not SQLite.** A container filesystem is wiped on every deploy,
so the default `lms.db` would take every account, attempt and payment record
with it each time you ship. `render.yaml` wires `DATABASE_URL` in for exactly
this reason; the app rewrites the URL to the psycopg3 driver on its own.

**Uploads have the same problem and no such fix.** `uploads/` is on the
container filesystem, so uploaded videos and notes vanish on redeploy. Lectures
added as YouTube/Vimeo links are unaffected. Moving uploads to S3 or a mounted
disk is the prerequisite for taking file uploads seriously in production.

## Security checklist before deploying

- [ ] Set a real `SECRET_KEY` (`python -c "import secrets; print(secrets.token_urlsafe(48))"`)
- [ ] `SHOW_DEMO_CREDENTIALS=false` (the default) — printing `admin / admin123`
      on a public sign-in page is a login bypass, not a convenience
- [ ] Change the seeded `admin` password, or delete the account. Hiding the
      credentials does not make `admin123` any harder to guess
- [ ] `SEED_DEMO_DATA=false`, and delete the `admin`/`teacher`/`student` accounts
- [ ] `DEBUG=false`
- [ ] Serve over HTTPS and add `secure=True` to the session cookie in `routers/auth.py`
- [ ] Self-host Jitsi and set `MEET_DOMAIN` if class content is confidential
- [ ] Put a reverse proxy in front with request size limits and rate limiting
- [ ] Back up `uploads/` alongside the database; the two are useless apart
