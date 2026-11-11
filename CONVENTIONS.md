```text
ADMIN SITE CODING CONVENTIONS

The contract every developer and AI agent follows when writing code in the admin site
(Django). It carries the backend services' conventions over to Django: same layering idea,
same quality gate, same rules for agents. Where Django already does a job (forms, migrations,
the ORM for the site's own tables), use Django's way instead of copying a service pattern.

Format with `make fix`; `make check` must pass before pushing (pre-commit + CI enforce it).


THE BIG RULE: THREE LAYERS

- views (tenants/views.py, analytics/views.py, accounts/views.py)
    Read the request, call a selector, build charts, render. No data shaping, no RPC.
- selectors (tenants/selectors.py, tenants/user_selectors.py, analytics/selectors.py)
    Combine several services' query results into what a page shows. No rendering.
- servicedata
    The only code that talks to the services: rpc.py (RabbitMQ RPC), contracts.py (reply
    shapes), stats.py (Sources: per-request degradation; date series), tiers.py (limits).
    It never imports the apps or the `admin` project package.

- tenants and analytics are independent of each other; shared UI helpers live in admin/
  (admin/charts.py). accounts does not depend on the data pages.
- These boundaries are enforced by import-linter (.importlinter), not just by review.
- The admin site never connects to a service database and never writes service data. New
  service data = a new query in the owning service's `features/admin_query` (SQL in that
  service's repository) plus its contract in servicedata/contracts.py.


SERVICE DATA AND CONTRACTS

- Every query the site calls has a reply contract in servicedata/contracts.py REPLIES.
  rpc.query validates every reply against it; a reply that breaks it raises
  ServiceUnavailable, so the page shows the service as down instead of failing.
- Declare a field as UtcDatetime or date only when it is one. Never parse values by guessing
  from their shape: customer-typed text can look like a date.
- Declare every key the pages read. Keys not declared are dropped.
- Read services through `Sources.query(service, name, default, **params)` in selectors. A
  failed service returns `default`, is skipped for the rest of the request, and is named in
  the page banner. Pick a `default` the page can render.
- Log contract violations by location only (field path + error type), never values: replies
  carry decrypted names and emails.


ERRORS

- Service failures are expected: degrade (banner + default), never 500.
- A missing object with Identity up is a 404; with Identity down, the "unavailable" page.
- Use logger.exception(...) inside except blocks. Never swallow an exception silently.


SECURITY

- Gate every page with @view_required and every write or download with @edit_required
  (accounts/decorators.py). Employee management uses manage_required.
- POST for anything that changes state (@require_POST); keep {% csrf_token %} in forms.
- Chart data goes to the page with |json_script, never |safe.
- Nothing secret in code: configuration comes from the environment (admin/settings.py,
  .env.example). Sentry runs with send_default_pii=False.
- Every request by a signed-in employee is recorded in AccessLog (accounts/middleware.py).


DJANGO SPECIFICS

- The site's own tables (employees, sessions, access log) use Django models and migrations.
  `make check` fails when models and migrations differ.
- Forms keep Django's contracts: save(commit=False) must not write anything (see
  EmployeeFormBase.save).
- WSGI only: rpc.py keeps a blocking connection per thread. There is no ASGI entry point.


TYPING AND DOCUMENTATION

- Type-annotate every function outside tests and migrations. `make type-check` (pyright,
  basic, with django-stubs) is advisory in CI, as in the services, but keep it at 0 errors.
- Docstring on every module, class and public function: what it does; args/returns/raises
  where not obvious from the signature. Update the docstring in the same edit as the code.


TESTING

- Write the failing test first (bug: reproduce it; feature: expected behaviour).
- Pure helpers: SimpleTestCase. Pages: servicedata.fake_replies.PageTestCase, which signs in
  a Monitor and answers every query from fake_replies.replies() through the real decoding
  and contract validation. Override replies with self.answer({...}), fail every service with
  self.fail_all().
- When a query or its contract changes, update fake_replies.replies(); a test checks that
  every contract has a fake reply that passes it.
- Test emails use @yopmail.com.
- `make test`, `make coverage`.


SIZE, COMPLEXITY, NAMING

- No file longer than 500 lines; no copy-pasted blocks of 8+ lines (pylint).
- Complexity gate (xenon): no function worse than C, no module worse than B, average A.
  Stricter than the services' D/D/B: keep it there.
- Descriptive names: no single-letter or cryptic locals outside comprehensions and tiny
  lambdas (`identity`, `detail`, `day_labels`, not `d`, `idn`, `x`).
- Template context keys may stay short where templates already use them.


LINTING & FORMATTING

`make check` runs: ruff format --check, ruff lint (ruff.toml: the services' rule set + DJ),
pylint (500-line cap, duplicate code), xenon, import-linter, `manage.py check` and
`makemigrations --check`. `make deploy-check` runs Django's deployment checklist against
production-like settings. Never add `# noqa`, `# type: ignore` or `--no-verify` to silence
a finding: fix the code, or leave the finding for a human to review.


CONFIG FILES (AI agents only)

- AI agents must not change config files (ruff.toml, .pylintrc, .importlinter,
  pyrightconfig.json, Makefile, CI workflows, pre-commit) to ease a code change or shortcut
  a fix. Raise a needed config change with the human developer first.


GIT (AI agents only)

- AI agents never commit, branch, push, stage or move files with git without explicit
  approval. They leave changes uncommitted for a human to review.
```
