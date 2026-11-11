# Pro3AI admin site: local development and the quality gate.
# `make fix` formats and auto-fixes; `make check` must pass before pushing (pre-commit + CI).
# Install the tools once with: pip install -r requirements-dev.txt && pre-commit install

PYTHON ?= python
APPS = accounts admin analytics servicedata tenants

.PHONY: help run migrate test coverage fix check type-check deploy-check

help:
	@echo "make run | migrate | test | coverage | fix | check | type-check | deploy-check"

run:
	$(PYTHON) manage.py runserver

migrate:
	$(PYTHON) manage.py migrate

test:
	$(PYTHON) manage.py test

coverage:
	$(PYTHON) -m coverage run --source=. --omit="*/migrations/*,*/tests.py,manage.py" manage.py test
	$(PYTHON) -m coverage report

fix:
	ruff format . && ruff check . --fix

# Format, lint, file size + duplicate code, complexity, layer boundaries, Django's own checks
# and migrations in step with the models.
check:
	ruff format --check .
	ruff check .
	pylint $(APPS)
	xenon --max-absolute C --max-modules B --max-average A --exclude "*/migrations/*" .
	lint-imports --config .importlinter
	$(PYTHON) manage.py check
	$(PYTHON) manage.py makemigrations --check --dry-run

# Advisory, as in the services.
type-check:
	pyright

# Django's deployment checklist against production-like settings.
deploy-check:
	DJANGO_DEBUG=false DJANGO_ALLOWED_HOSTS=admin.example.com EMAIL_HOST=smtp.example.com \
	  $(PYTHON) manage.py check --deploy --fail-level WARNING
