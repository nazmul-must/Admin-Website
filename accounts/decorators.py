from django.contrib.auth.decorators import login_required, permission_required

from .models import EDIT_SITE, VIEW_SITE


def role_required(perm):
    """Anonymous users go to the login page; signed-in users without `perm` get 403."""

    def decorator(view):
        return login_required(permission_required(perm, raise_exception=True)(view))

    return decorator


view_required = role_required(VIEW_SITE)  # Monitor and above
edit_required = role_required(EDIT_SITE)  # Manager and above
