import os
from pathlib import Path

import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent
DEBUG = os.environ.get("DEBUG", "false").lower() == "true"
SECRET_KEY = os.environ.get("SECRET_KEY", "")
if not SECRET_KEY:
    if not DEBUG:
        raise RuntimeError("SECRET_KEY must be supplied (or use DEBUG=true locally).")
    SECRET_KEY = "development-only-do-not-use-in-production"
ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1,testserver").split(",")
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]
# Render supplies this environment value; never derive trust from request headers.
render_hostname = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "").strip()
if render_hostname:
    ALLOWED_HOSTS.append(render_hostname)
    CSRF_TRUSTED_ORIGINS.append(f"https://{render_hostname}")
INSTALLED_APPS = [
    "config.apps.AuditedAdminConfig",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.forms",
    "accounts",
    "core",
    "suppliers",
    "quality",
    "catalog",
    "sampling",
    "reporting",
    "pagedocs",
    "analytical",
    "laboratory",
    "stability",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "config.security.ContentSecurityPolicyMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    # Ahead of the CSRF check, which is the first code to read a submitted form.
    "core.uploads.UploadSizeMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "core.session_control.ControlledSessionMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
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
                "accounts.context_processors.account_navigation",
                "core.context_processors.product",
            ]
        },
    }
]
DATABASES = {
    "default": dj_database_url.config(
        default="postgresql://open_qual:open_qual@127.0.0.1:55433/open_qual",
        conn_max_age=60,
        conn_health_checks=True,
    )
}
if test_database_name := os.environ.get("TEST_DATABASE_NAME"):
    if (
        not test_database_name.startswith("test_")
        or test_database_name == DATABASES["default"]["NAME"]
    ):
        raise RuntimeError("TEST_DATABASE_NAME must name a separate test_ database.")
    DATABASES["default"]["TEST"] = {"NAME": test_database_name}
AUTH_USER_MODEL = "accounts.User"
# Only the throttled backend: a second backend would accept credentials refused during a lock.
AUTHENTICATION_BACKENDS = ["accounts.authentication.ThrottledModelBackend"]
LOGIN_FAILURE_LIMIT = int(os.environ.get("LOGIN_FAILURE_LIMIT", "5"))
LOGIN_LOCK_SECONDS = int(os.environ.get("LOGIN_LOCK_SECONDS", "900"))
if LOGIN_FAILURE_LIMIT < 1 or LOGIN_LOCK_SECONDS < 60:
    raise RuntimeError("Sign-in throttling needs LOGIN_FAILURE_LIMIT >= 1, LOCK_SECONDS >= 60.")
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
# Sign-in events go to standard output so they survive database resets (accounts.signin_log).
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"masked": {"()": "config.security.CredentialLogFormatter"}},
    "handlers": {
        "stdout": {
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
            "formatter": "masked",
        }
    },
    "loggers": {"openbga.signin": {"handlers": ["stdout"], "level": "INFO", "propagate": False}},
}
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/accounts/login/"
EMAIL_BACKEND = os.environ.get(
    "EMAIL_BACKEND",
    "django.core.mail.backends.console.EmailBackend"
    if DEBUG
    else "django.core.mail.backends.dummy.EmailBackend",
)
EMAIL_HOST = os.environ.get("EMAIL_HOST", "")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "true").lower() == "true"
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "noreply@example.invalid")
LANGUAGE_CODE = "en-us"
TIME_ZONE = os.environ.get("TIME_ZONE", "UTC")
USE_I18N = True
USE_TZ = True
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"] if (BASE_DIR / "static").exists() else []
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_SSL_REDIRECT = not DEBUG
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
# One year once HTTPS is confirmed; subdomain/preload scope is an explicit operator choice.
SECURE_HSTS_SECONDS = 0 if DEBUG else int(os.environ.get("SECURE_HSTS_SECONDS", "31536000"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = (
    os.environ.get("SECURE_HSTS_INCLUDE_SUBDOMAINS", "false").lower() == "true"
)
SECURE_HSTS_PRELOAD = os.environ.get("SECURE_HSTS_PRELOAD", "false").lower() == "true"
X_FRAME_OPTIONS = "DENY"
# Vendored assets only: no inline script/style, eval, external origins or framing.
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; "
    "form-action 'self'; frame-ancestors 'none'"
)
DEFAULT_EXCEPTION_REPORTER = "config.security.CredentialExceptionReporter"
DEFAULT_EXCEPTION_REPORTER_FILTER = "config.security.CredentialExceptionReporterFilter"
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 1024 * 1024
# core.uploads.UploadSizeMiddleware refuses an upload that declares too large a body before it
# is read; the first handler stops a file that exceeds RAW_DATA_MAX_BYTES while it is received.
FILE_UPLOAD_HANDLERS = [
    "core.uploads.BoundedUploadHandler",
    "django.core.files.uploadhandler.MemoryFileUploadHandler",
    "django.core.files.uploadhandler.TemporaryFileUploadHandler",
]

FORM_RENDERER = "django.forms.renderers.TemplatesSetting"

# AGPL-3.0 section 13: link users to the source of the running version. Point this at your own
# repository when you deploy a modified version.
SOURCE_CODE_URL = os.environ.get("SOURCE_CODE_URL", "https://github.com/openbga/fresh-coa-lims")

REPORT_SYNTHETIC_DATA_NOTICE = (
    os.environ.get("REPORT_SYNTHETIC_DATA_NOTICE", "true").lower() == "true"
)

# Product defaults; deployers validate these against their controlled-access procedures.
SESSION_IDLE_SECONDS = int(os.environ.get("SESSION_IDLE_SECONDS", "900"))
SESSION_ABSOLUTE_SECONDS = int(os.environ.get("SESSION_ABSOLUTE_SECONDS", "28800"))
if not 60 <= SESSION_IDLE_SECONDS <= SESSION_ABSOLUTE_SECONDS:
    raise RuntimeError("Session limits must satisfy 60 <= idle <= absolute.")
SESSION_COOKIE_AGE = SESSION_ABSOLUTE_SECONDS
SESSION_EXPIRE_AT_BROWSER_CLOSE = True

FORMS_URLFIELD_ASSUME_HTTPS = True

ANALYTICAL_REQUIREMENT_PROVIDER = "config.integrations.CatalogRequirementProvider"
# Result entry asks the laboratory module whether the analyst is qualified for the method and
# whether each selected instrument and reagent or standard lot is fit for use. Without this
# setting results are held.
ANALYTICAL_BENCH = "config.integrations.LaboratoryBench"
# Raw-data files are stored in PostgreSQL with their test. This is the largest file accepted,
# in bytes; each upload is held in memory while its checksum is calculated.
RAW_DATA_MAX_BYTES = int(os.environ.get("RAW_DATA_MAX_BYTES", str(10 * 1024 * 1024)))
if not 1 <= RAW_DATA_MAX_BYTES <= 50 * 1024 * 1024:
    raise RuntimeError("RAW_DATA_MAX_BYTES must be from 1 to 52428800 (50 MiB).")
# Optional ceiling on all raw-data files of the deployment together, in bytes; 0 sets none.
RAW_DATA_TOTAL_MAX_BYTES = int(os.environ.get("RAW_DATA_TOTAL_MAX_BYTES", "0"))
if RAW_DATA_TOTAL_MAX_BYTES < 0:
    raise RuntimeError("RAW_DATA_TOTAL_MAX_BYTES must be 0 (no ceiling) or a positive size.")
