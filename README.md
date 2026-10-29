# Pro3AI Admin Site

An internal administration application for **Pro3AI platform operators and the company owner**.
It gives a cross-tenant view of the whole platform: every organization, every user, billing,
AI spend, adoption and access decisions. Later it will also let operators act on them.

It is **not** for customer organizations. Customer org admins keep using the org-admin screens
inside Pro3AI-Frontend (members, roles, organisation settings, billing).

---

## Why a separate application

Three requirements drive the design:

1. **It must stay up when the product is down.** If the product cluster, a service or its
   database fails, operators still need to log in and see what is broken and since when. So the
   admin site is deployed separately from the product, with its own database and login.
2. **Operator powers stay off the customer attack surface.** Nothing here goes through the
   customer Apollo Router, the shared `JWT_SECRET`, or the customer frontend bundle.
3. **The admin site never writes to a service database.** Every change must go through the
   service that owns the data, so PII encryption, sagas, cache invalidation and RBAC sync stay
   correct. This is enforced in code today (see `admin/db_router.py`).

Grafana, Prometheus, Loki and Tempo already cover service health: request rates, errors,
latency, the outbox and logins. The admin site does **not** repeat that. It covers what Grafana
has no data for: tenants, subscriptions, AI credits, feature adoption and access decisions.

---

## Target architecture

```
MANAGEMENT PLANE (separate small OKE cluster, ideally another region)
┌───────────────────────────────────────────────────────────────┐
│ Admin site (Django) — one image, two processes                 │
│   web:    UI, operator login (SSO + MFA), sessions, actions    │
│   worker: health prober, alerting, scheduled jobs              │
│ Managed PostgreSQL: operators, sessions, audit, health history │
│ Own ArgoCD                                                     │
│ (later) Prometheus/Mimir, Loki, Tempo, Grafana, Alertmanager   │
└───────────────────────────────┬───────────────────────────────┘
                                │ private link + mTLS
                                ▼
PRODUCT PLANE (existing OKE)
┌───────────────────────────────────────────────────────────────┐
│ Each service: internal admin API (not in the public graph)     │
│ /health on every service, RabbitMQ management API              │
└───────────────────────────────────────────────────────────────┘
```

| Concern | Decision |
|---|---|
| Framework | Django 6.x, server-rendered templates |
| UI | Tailwind (standalone CLI, no Node) + HTMX for partial updates + Chart.js for graphs |
| Own database | Managed PostgreSQL, outside the product cluster's failure domain |
| Reading service data | Each service's internal admin API |
| Changing service data | Admin API call on the **owning** service; that service publishes RabbitMQ events as it does today |
| Long operations (reconcile, re-ingest, RBAC resync) | Admin API starts the job in the service; the admin site polls status |
| Live status | HTMX polling; upgrade path is Postgres `LISTEN/NOTIFY` + SSE, no Redis |
| Operator auth | SSO + MFA (`django-allauth`), credentials separate from the customer `JWT_SECRET` |
| Hosting | Dedicated management OKE cluster with its own ArgoCD; secrets in OCI Vault |

RabbitMQ is not used as a query API for the admin site. It stays the backbone between services.

The full reasoning is in `personal/admin-app/00-overview.md`.

---

## Where we are now (local prototype)

The current code is a working **local** prototype. It runs against the local Docker stack and
shows real data. Built so far:

| Area | Pages | What they show |
|---|---|---|
| Overview | `/` | Platform totals, signup and growth charts, tier and status mix, "needs attention" list, newest organizations |
| Organizations | `/orgs/`, `/orgs/<id>/` | Search and filters; per-org tier, status, users and programmes vs limits, AI credits vs allowance, documents, last activity. Detail page: subscription and Stripe data, limits vs usage, activity/AI/access/document charts, programmes, memberships, audit log |
| Users | `/users/`, `/users/<id>/` | Search by name, email or ID; filters by org, email verification, MFA. Detail page: memberships, access/AI/upload charts, denials, notifications, actions by and changes to the user |
| Growth | `/analytics/growth/` | Signups per day, cumulative growth, org types, activation funnel (signup → 2nd user → programme → work items → documents → AI) |
| Billing | `/analytics/billing/` | Tier × status, renewals in 30 days, problem subscriptions, limit overrides, Stripe webhook events |
| AI usage | `/analytics/ai/` | Credits and tokens per day, by model and feature, top orgs vs allowance, plan-run failures, ingestion, per-org key health |
| Engagement | `/analytics/engagement/` | Weekly/monthly active members, daily active members and orgs, feature adoption, dormant orgs |
| Access | `/analytics/access/` | Allowed vs denied permission checks, deny rate, denials by action and reason, most-denied members |

Behaviour worth knowing:

- **A failed service does not break a page.** If one service database is unreachable, the page
  shows a banner naming it and renders everything else (`servicedata/stats.py`, `Sources`).
- **Read-only.** Service models are unmanaged; the database router refuses writes and migrations.
- **PII.** User names and emails are decrypted only when `MASTER_SECRET_KEY` is set in `.env`;
  otherwise the pages show the encrypted values.

### Prototype shortcuts to remove before deploying

| Shortcut | Replace with |
|---|---|
| Direct read-only connections to six service Oracle PDBs | Each service's internal admin API |
| Identity's `MASTER_SECRET_KEY` in the admin `.env` to decrypt names/emails | Identity decrypts on its side and returns plaintext through its admin API |
| Tier limits read from `../Identity-Backend/app/initialize_app/tier.config.json` | Served by Identity's admin API |
| SQLite for Django's own tables | Managed PostgreSQL |
| Django's built-in username/password login (`/login/`) | Operator SSO + MFA |
| Tailwind, HTMX and Chart.js loaded from a CDN | Tailwind standalone CLI build and vendored JS |
| User search decrypts every user in Python | Search through Identity |
| No pagination on lists | Paginated lists |

---

## Roadmap

Each step gets its own design, plan and build. Read before write; impersonation only after audit
exists; the monitoring move once the management cluster is stable.

| # | Step | Scope |
|---|---|---|
| 0 | **Foundation** | Management cluster + Postgres, operator login (SSO/MFA), operator audit log, private link + mTLS to services, admin credentials separate from `JWT_SECRET`, first service admin API |
| 1 | Tenants and users, read-only | Move the existing pages from direct DB reads to service admin APIs |
| 2 | Write actions + enterprise provisioning | Suspend/reactivate org, disable user, force logout, MFA reset, create an enterprise org without signup |
| 3 | Billing oversight | Stripe sync status, manual overrides (trial extension, seats, AI allowance) |
| 4 | RBAC ops | Global roles and permissions, `rbac_hierarchy_mv` resync trigger, "why was this denied" |
| 5 | Platform health + ops actions | Outside-in health prober, RabbitMQ queues and DLQs, app-init status, reconcile / re-ingest / cache bust |
| 6 | Cross-tenant audit | Who did what, across tenants |
| 7 | Impersonation | Short-lived customer token with an `act` claim, read-only by default |
| 8 | Analytics | Move heavy analytics to Data-Vault/Airbyte data instead of live service databases |
| 9 | Monitoring move | Grafana and the observability stack move to the management plane; in-cluster agents remote-write out |

Open questions for Foundation: SSO provider and invitation flow, the shape of each service's
admin API (internal GraphQL schema or REST), admin → service authentication and key rotation,
region for the management plane, and moving Agent-Backend's `/api/v1/admin/reconcile` behind the
new trust boundary.

---

## Running locally

Requires the local product stack (Oracle on `localhost:1521`) and the `mtr-env` conda Python.

```bash
cp .env.example .env          # fill ORACLE_PASSWORD; MASTER_SECRET_KEY is optional
pip install -r requirements.txt
python manage.py migrate      # Django's own tables only, in db.sqlite3
python manage.py createsuperuser
python manage.py runserver    # http://127.0.0.1:8000/
python manage.py test
```

## Employees and roles

**Employees** are the people who sign in to this admin site. They are not **users**: users are the
customers of Pro3AI, read from the Identity service and shown under *Users*. Super Admins manage
employees under *Employees* in the sidebar (`/employees/`). Every employee has exactly one role,
required when the employee is added. Each role is a
Django group, created by the `accounts` migration.

| Role | Can | Permissions |
|---|---|---|
| Super Admin | Everything, plus add employees and assign their roles | `view_site`, `edit_site`, `manage_employees` + Employee admin |
| Manager | View every page; edit, modify and download | `view_site`, `edit_site` |
| Monitor | View every page, read-only | `view_site` |

`createsuperuser` accounts count as Super Admin too; use one to add the first employees. An employee
with no role can sign in but gets "No permission" on every page. Gate new pages with `@view_required` and new
write or download actions with `@edit_required` (`accounts/decorators.py`); in templates, use
`{% if perms.accounts.edit_site %}`.

## Code layout

| Path | Contents |
|---|---|
| `admin/` | Settings, URLs, read-only database router, nav and role context processors |
| `accounts/` | Employees (admin-site accounts) and their roles: permissions, Employee admin, the migration that creates the role groups, view decorators, tests |
| `servicedata/` | Read-only models over service tables, query helpers (`stats.py`), tier limits, PII decryption, template filters, tests |
| `tenants/` | Organization and user list/detail pages |
| `analytics/` | Overview and analytics pages, Chart.js config builder |
| `templates/` | Base layout, theme, login, 403 page and shared partials (KPI card, chart, window picker, user cell) |
| `static/js/charts.js` | Renders server-built Chart.js configs, also after HTMX swaps |

Oracle traps for anyone adding models: Django truncates unquoted names over 30 characters
(pre-quote `db_column`), and it uppercases every name, so lowercase-quoted columns such as
`document_versions."size"` need `RawSQL`.
