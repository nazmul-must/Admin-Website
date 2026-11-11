"""Django settings for the Pro3AI admin site.

Everything that differs between a laptop and a deployment comes from the environment (or the
gitignored `.env`); see `.env.example`. Nothing secret lives in this file.
Reference: https://docs.djangoproject.com/en/6.1/ref/settings/
"""

import os
from pathlib import Path

import sentry_sdk
from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env_bool(name: str, default: bool = False) -> bool:
    """A true/false environment variable: 1, true, yes or on mean true."""
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def env_list(name: str) -> list[str]:
    """A comma-separated environment variable as a list (empty entries dropped)."""
    return [item.strip() for item in os.environ.get(name, "").split(",") if item.strip()]


# ----- Core --------------------------------------------------------------------------------

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    raise ImproperlyConfigured(
        "Set DJANGO_SECRET_KEY (see .env.example). "
        'Generate one with: python -c "import secrets; print(secrets.token_urlsafe(50))"'
    )
DEBUG = env_bool("DJANGO_DEBUG")
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS")  # empty + DEBUG = localhost only
ENVIRONMENT = os.environ.get("ENVIRONMENT", "DEV")  # DEV / TEST / PROD, as in the services

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "accounts",
    "servicedata",
    "tenants",
    "analytics",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "accounts.middleware.AccessLogMiddleware",
]

ROOT_URLCONF = "admin.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "admin.context_processors.nav",
                "admin.context_processors.role",
            ],
        },
    },
]

# WSGI only: servicedata/rpc.py keeps a blocking RabbitMQ connection per thread.
WSGI_APPLICATION = "admin.wsgi.application"

# Django's own tables (employees, sessions, access log). SQLite locally; the deployment
# points DB_ENGINE and friends at managed PostgreSQL (needs psycopg in requirements.txt).
DATABASES = {
    "default": {
        "ENGINE": os.environ.get("DB_ENGINE", "django.db.backends.sqlite3"),
        "NAME": os.environ.get("DB_NAME", str(BASE_DIR / "db.sqlite3")),
        "USER": os.environ.get("DB_USER", ""),
        "PASSWORD": os.environ.get("DB_PASSWORD", ""),
        "HOST": os.environ.get("DB_HOST", ""),
        "PORT": os.environ.get("DB_PORT", ""),
    },
}

# ----- Service data ------------------------------------------------------------------------

# Service data comes from each service's admin read queries over RabbitMQ RPC
# (servicedata/rpc.py), never from service databases. RABBITMQ_SUFFIX must match the
# services' RABBITMQ_SUFFIX: pro3ai_generic appends it to every routing key.
RABBITMQ_URL = os.environ.get("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/")
RABBITMQ_SUFFIX = os.environ.get("RABBITMQ_SUFFIX", "")
# Seconds to wait for one service's reply before showing it as down.
ADMIN_RPC_TIMEOUT = float(os.environ.get("ADMIN_RPC_TIMEOUT", "8"))

# ----- Sign-in -----------------------------------------------------------------------------

# Roles (Super Admin, Manager, Monitor) live in accounts/models.py. Role members are not
# Django staff, so everyone signs in through Django's own LoginView.
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "overview"
LOGOUT_REDIRECT_URL = "login"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ----- HTTPS (off with DEBUG) --------------------------------------------------------------

SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_SSL_REDIRECT = env_bool("DJANGO_SSL_REDIRECT", not DEBUG)
SECURE_REDIRECT_EXEMPT = [r"^health/$"]  # probes call the pod over plain HTTP
SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_HSTS_SECONDS", "0" if DEBUG else "31536000"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG  # covers only subdomains of the admin host itself
# HSTS preload needs the apex domain, which the admin site does not own: not applicable.
SILENCED_SYSTEM_CHECKS = ["security.W021"]
if env_bool("DJANGO_BEHIND_TLS_PROXY"):
    # Only behind an ingress that sets this header itself (and drops a client's copy).
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# ----- Locale and static files -------------------------------------------------------------

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]

# ----- Email -------------------------------------------------------------------------------

# SMTP when EMAIL_HOST is set; otherwise emails are printed in the runserver terminal.
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "webmaster@localhost")
if os.environ.get("EMAIL_HOST"):
    MAILERS = {
        "default": {
            "BACKEND": "django.core.mail.backends.smtp.EmailBackend",
            "OPTIONS": {
                "host": os.environ["EMAIL_HOST"],
                "port": int(os.environ.get("EMAIL_PORT", "587")),
                "username": os.environ.get("EMAIL_HOST_USER", ""),
                "password": os.environ.get("EMAIL_HOST_PASSWORD", ""),
                "use_tls": env_bool("EMAIL_USE_TLS", True),
            },
        },
    }
else:
    MAILERS = {"default": {"BACKEND": "django.core.mail.backends.console.EmailBackend"}}

# ----- Logging and errors (same shape as the services' logging_conf.py) --------------------

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {"()": "admin.log_format.JsonFormatter"},
        "plain": {"format": "%(asctime)s - [%(name)s] - %(levelname)s - %(message)s"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
            "formatter": "json" if ENVIRONMENT == "PROD" else "plain",
        },
    },
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
    "loggers": {"pika": {"level": "WARNING"}},  # one line per connection otherwise
}

if os.environ.get("SENTRY_DSN"):
    sentry_sdk.init(
        dsn=os.environ["SENTRY_DSN"],
        environment=ENVIRONMENT,
        send_default_pii=False,  # pages hold decrypted customer names and emails
        traces_sample_rate=float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0")),
    )
