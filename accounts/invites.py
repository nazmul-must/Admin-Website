"""Sign-in links: the emailed, one-time link where an employee chooses a password. For an
unverified employee that verifies their email; for a verified one it resets the password.
The link dies once used, or after PASSWORD_RESET_TIMEOUT."""

import logging

from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from .models import email_verified

logger = logging.getLogger(__name__)


def email_sign_in_link(employee, base_url):
    """Email the link. `base_url` is the site root, e.g. http://localhost:8000. Raises on mail failure."""
    uid = urlsafe_base64_encode(force_bytes(employee.pk))
    token = default_token_generator.make_token(employee)
    context = {
        'employee': employee,
        'verified': email_verified(employee),
        'link': base_url.rstrip('/') + reverse('employee-verify', args=[uid, token]),
        'days': settings.PASSWORD_RESET_TIMEOUT // 86400,
    }
    subject = 'Reset your Pro3AI Admin password' if context['verified'] else 'Verify your email for Pro3AI Admin'
    send_mail(subject, render_to_string('accounts/email/sign_in_link.txt', context), None, [employee.email])
    if settings.DEBUG:
        # The console mailer wraps long lines (quoted-printable), which breaks the link; log it whole.
        logger.warning('Sign-in link for %s: %s', employee.email, context['link'])
