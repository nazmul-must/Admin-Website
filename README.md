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
   correct. The admin site has no connection to any service database at all.

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
| Reading service data | Each service's admin read queries over RabbitMQ RPC (CQRS query side, see below) |
| Changing service data | Admin API call on the **owning** service; that service publishes RabbitMQ events as it does today |
| Long operations (reconcile, re-ingest, RBAC resync) | Admin API starts the job in the service; the admin site polls status |
| Live status | HTMX polling; upgrade path is Postgres `LISTEN/NOTIFY` + SSE, no Redis |
| Operator auth | SSO + MFA (`django-allauth`), credentials separate from the customer `JWT_SECRET` |
| Hosting | Dedicated management OKE cluster with its own ArgoCD; secrets in OCI Vault |

Reads go over RabbitMQ RPC (decided 2026-10-29, replacing the earlier "internal HTTP admin API"
plan): the services already answer RPC queries this way, so no new HTTP surface is needed.

### Admin read queries (CQRS query side)

Each service runs one consumer on the `admin` exchange, routing key `admin.query.<service>`
(plus the services' `RABBITMQ_SUFFIX`), in its `admin_query` feature. A request is
`{"query": name, "params": {...}}`; the reply is `{"status": "success", "data": ...}` or
`{"status": "error", "message": ...}`, sent through RabbitMQ direct reply-to. Queries are
read-only and shaped for the admin pages (daily counts, counts by field, per-org totals), so the
SQL stays in the owning service and only small results cross the broker. The admin site merges
results across services (`servicedata/rpc.py` is the client).

| Service | Queries |
|---|---|
| Identity | `tiers`, `subscriptions`, `directory`, `org_list`, `org_detail`, `user_list`, `user_detail`, `overview`, `growth`, `billing_events` |
| Agent | `org_usage`, `org_detail`, `member_usage`, `dashboard` |
| Authorization | `member_last_access`, `member_access`, `engagement`, `access` |
| Document | `summary`, `org_detail`, `member_uploads` |
| Planning | `summary`, `programme_items` |
| Notification | `member_notes`, `unread_by_member` |

Identity decrypts user names and emails on its side; the admin site never holds the PII key.

Writes (the command side, roadmap step 2) will be separate commands handled by the owning
service, never by these query consumers.

**Before deploying:** anything that can publish to the `admin` exchange can read cross-tenant
data, including decrypted names and emails. Give the admin site its own RabbitMQ user, and give
only that user write permission on the `admin` exchange. Service users need configure/read on it
(to declare and bind their queues) but not write.

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

- **A failed service does not break a page.** If a service does not reply within
  `ADMIN_RPC_TIMEOUT` seconds (default 8), or has no consumer bound, the page shows a banner
  naming it and renders everything else (`servicedata/stats.py`, `Sources`).
- **Replies are checked.** Every reply is validated against its contract in
  `servicedata/contracts.py` before a page reads it. A service whose reply has changed shape
  is shown in the same banner as a down service, never as a 500. Only fields declared as
  dates are parsed as dates.
- **Read-only.** The admin site only sends read queries; it has no database connection to any service.
- **Access log.** Every request a signed-in employee makes is recorded (`AccessLog`), with
  the full path, so searches are recorded too.
- **Health.** `/health/` answers 200 while the site's own database does, without sign-in.
  It does not check the product services: the site must stay up when they are down.
- **PII.** Identity returns names and emails decrypted. A user whose fields Identity cannot
  decrypt is shown by id.

### Prototype shortcuts to remove before deploying

| Shortcut | Replace with |
|---|---|
| Shared RabbitMQ user for the admin site and the services | Admin-only RabbitMQ user with sole write permission on the `admin` exchange |
| Admin RPC calls on one page run one after another | Publish them together and collect replies by correlation id |
| SQLite for Django's own tables | Managed PostgreSQL (set `DB_*` in the environment and add `psycopg`) |
| Django's built-in username/password login (`/login/`), throttled per email in the per-process cache | Operator SSO + MFA |
| Tailwind, HTMX and Chart.js loaded from a CDN | Tailwind standalone CLI build and vendored JS |
| Identity returns every user and the search runs in the admin site | Search and paging inside Identity's `user_list` query |
| No pagination on lists | Paginated lists |

---

## Roadmap

Each step gets its own design, plan and build. Read before write; impersonation only after audit
exists; the monitoring move once the management cluster is stable.

| # | Step | Scope |
|---|---|---|
| 0 | **Foundation** | Management cluster + Postgres, operator login (SSO/MFA), operator audit log, private link + mTLS to services, admin credentials separate from `JWT_SECRET`, first service admin API |
| 1 | Tenants and users, read-only | Done: the existing pages read through service admin RPC queries |
| 2 | Write actions + enterprise provisioning | Suspend/reactivate org, disable user, force logout, MFA reset, create an enterprise org without signup |
| 3 | Billing oversight | Stripe sync status, manual overrides (trial extension, seats, AI allowance) |
| 4 | RBAC ops | Global roles and permissions, `rbac_hierarchy_mv` resync trigger, "why was this denied" |
| 5 | Platform health + ops actions | Outside-in health prober, RabbitMQ queues and DLQs, app-init status, reconcile / re-ingest / cache bust |
| 6 | Cross-tenant audit | Who did what, across tenants |
| 7 | Impersonation | Short-lived customer token with an `act` claim, read-only by default |
| 8 | Analytics | Move heavy analytics to Data-Vault/Airbyte data instead of live service databases |
| 9 | Monitoring move | Grafana and the observability stack move to the management plane; in-cluster agents remote-write out |

Open questions for Foundation: SSO provider and invitation flow, how the management cluster
reaches the product RabbitMQ (private link, or a shovel/federation), admin RabbitMQ credentials and rotation,
region for the management plane, and moving Agent-Backend's `/api/v1/admin/reconcile` behind the
new trust boundary.

---

## Running locally

Requires the local product stack running (RabbitMQ on host port `5673`, and the services, which
answer the admin queries) and the `mtr-env` conda Python.

```bash
cp .env.example .env          # set DJANGO_SECRET_KEY, RABBITMQ_URL (services' user/password) and RABBITMQ_SUFFIX
pip install -r requirements-dev.txt   # app + quality tools; pre-commit install
make migrate                  # Django's own tables only, in db.sqlite3
python manage.py create_super_admin   # asks for your email and password; no verification
make run                      # http://127.0.0.1:8000/, sign in with that email
make test                     # or: make coverage
make fix && make check        # format, then the lint gate (also run by pre-commit and CI)
```

Coding rules for this repo are in [CONVENTIONS.md](CONVENTIONS.md).

## Employees and roles

**Employees** are the people who sign in to this admin site. They are not **users**: users are the
customers of Pro3AI, read from the Identity service and shown under *Users*. Super Admins manage
employees under *Employees* in the sidebar (`/employees/`). Every employee needs an **email**,
which is how they sign in, and exactly one role. Both are required when the employee is added.

New employees get an email with a one-time link (valid 3 days). Opening it and choosing a password
verifies the address; until then they can't sign in and the list shows *Awaiting verification*. A
Super Admin can resend the link from the employee's page, or send a password-reset link once the
employee is verified. Changing someone else's email makes them verify the new one. Locally the
console mailer prints emails in the runserver terminal, and in DEBUG the plain link is logged too
(the email body wraps it). Each role is a
Django group, created by the `accounts` migration.

| Role | Can | Permissions |
|---|---|---|
| Super Admin | Everything, plus add employees and assign their roles | `view_site`, `edit_site`, `manage_employees` |
| Manager | View every page; edit, modify and download | `view_site`, `edit_site` |
| Monitor | View every page, read-only | `view_site` |

Create the first Super Admin with `create_super_admin` (no email verification); they invite everyone
else, and those employees verify their email. `createsuperuser` accounts also count as Super Admin. An employee
with no role can sign in but gets "No permission" on every page. Gate new pages with `@view_required` and new
write or download actions with `@edit_required` (`accounts/decorators.py`); in templates, use
`{% if perms.accounts.edit_site %}`.

## Code layout

| Path | Contents |
|---|---|
| `admin/` | Settings (all from the environment), URLs, `/health/`, JSON log format, nav and role context processors, Chart.js config builder (`charts.py`) |
| `accounts/` | Employees (admin-site accounts) and their roles: permissions, the migration that creates the role groups, view decorators, sign-in throttling, the access log and its middleware, tests |
| `servicedata/` | RabbitMQ RPC client (`rpc.py`), reply contracts (`contracts.py`), per-request service access and date series (`stats.py`), subscriptions and tier limits (`tiers.py`), template filters, fake replies for tests |
| `tenants/` | Organization and user list/detail pages: views, and selectors that combine the services' data |
| `analytics/` | Overview and analytics pages: views (charts), and selectors that combine the services' data |
| `templates/` | Base layout, theme, login, 403 page and shared partials (KPI card, chart, window picker, user cell) |
| `static/js/charts.js` | Renders server-built Chart.js configs, also after HTMX swaps |

To show new service data, add a query to the owning service's `admin_query` feature (SQL in
that service's repository), add its reply contract to `servicedata/contracts.py` and a fake
reply to `servicedata/fake_replies.py`, and call it from a selector with
`src.query(service, name, default, **params)`.
