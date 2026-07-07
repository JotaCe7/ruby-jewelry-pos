# Ruby Jewelry POS — Backend

Django + Django REST Framework API backend for Joyería Ruby's ERP/POS system: inventory (Kardex), finance (multi-currency expenses), point of sale, and dashboard analytics.

This is an **API-only** backend. It has no templates or server-rendered pages — the UI lives in a separate project: [ruby-jewelry-pos-frontend](https://github.com/JotaCe7/ruby-jewelry-pos-frontend).

## Stack

- Python 3.12, managed with [uv](https://docs.astral.sh/uv/)
- Django 6 + Django REST Framework
- PostgreSQL (via Docker Compose for local dev)
- JWT auth (`djangorestframework-simplejwt`)
- `django-filter` for API filtering, `django-cors-headers` for the frontend origin

## Getting started

1. Copy the environment template and adjust if needed:

   ```bash
   cp .env.example .env
   ```

2. Start Postgres:

   ```bash
   docker compose up -d db
   ```

3. Install dependencies and run migrations:

   ```bash
   uv sync
   uv run python manage.py migrate
   uv run python manage.py createsuperuser
   ```

4. Run the dev server:

   ```bash
   uv run python manage.py runserver
   ```

   The API is available at `http://localhost:8000/api/`, and the Django admin at `http://localhost:8000/admin/`.

## Project layout

Each Django app owns one bounded area of the business domain:

| App | Responsibility |
|---|---|
| `core` | Shared base models (`TimeStampedModel`) and utilities |
| `catalogs` | Strict parent/child config catalogs: expense categories, payment methods, product categories/subcategories, colors, presentations |
| `contacts` | Suppliers and customers |
| `finance` | Expenses, multi-currency handling |
| `inventory` | Master product catalog, stock entries (unpacking), physical audits/shrinkage |
| `pos` | Sales and inventory exits (sale / gift / damaged), combo proration |
| `dashboard` | Read-only aggregation endpoints for KPIs and charts |
| `integrations` | External API clients (SUNAT exchange rate) and their local cache |

See the full architecture plan for data model details and business rules.

## Language conventions

All code (identifiers, comments) is written in English. User-facing strings (admin `verbose_name`s, API validation messages) go through Django's translation layer (`gettext`) — the product is built for a Spanish-speaking user, with `LANGUAGE_CODE = "es"` as the default and i18n scaffolding in place for future locales.
