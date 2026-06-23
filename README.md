# Fund Reporting Hub — Django edition

A complete **Django** rebuild of the original `reporting-hub.html` demo, backed
by **SQLite** with full **CRUD** across every entity, a dedicated **Database**
admin page, and the polished navy/slate UI from the original app.

## Features

- **Dashboard** — live metrics, validation progress by team, control consistency.
- **Reports** — search/filter, view, **create**, **edit**, **delete**; per-team
  validation sign-off; add/delete notes & disclaimers; status workflow.
- **Checks & Controls** — aggregate control health + catalogue of flagged reports.
- **Ad-hoc Chat** — DB-backed conversations with auto-replies; create/delete threads.
- **Database** — generic CRUD over every table (reports, controls, validations,
  notes, chats, messages) with insert/edit/delete and a one-click demo reset.
- **Django admin** — full built-in admin at `/django-admin/`.

## Project layout

```
django-reporting-hub/
├── manage.py
├── requirements.txt
├── db.sqlite3                 # created by migrate
├── fundhub/                   # project (settings, urls, wsgi/asgi)
├── reporting/                 # app
│   ├── models.py              # Report, Control, Validation, Note, Chat, Message
│   ├── views.py               # all page + CRUD views
│   ├── urls.py
│   ├── forms.py
│   ├── admin.py
│   └── management/commands/seed.py
└── templates/                 # base + one template per page
```

## Data model

- **Report** `id, fund, isin, type, period, lang, status`
- **Control** — per-report check results (`pass` / `warn` / `fail`)
- **Validation** — per-report, per-team sign-offs (`pending` / `approved` / `rejected`)
- **Note** — internal notes & disclaimers
- **Chat** / **Message** — ad-hoc chat threads

All child rows cascade-delete with their parent.

## Run it

```powershell
conda activate agenticai
pip install -r django-reporting-hub/requirements.txt

cd django-reporting-hub
python manage.py migrate
python manage.py seed          # load demo data (use --reset to reseed)
python manage.py runserver
```

Open http://127.0.0.1:8000/ in your browser.

### Optional: enable the Django admin

```powershell
python manage.py createsuperuser
```

Then sign in at http://127.0.0.1:8000/django-admin/.
