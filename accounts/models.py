"""Employees and their roles.

Employees are the people who sign in to this admin site. They are not Pro3AI users: those are
the customers of the product, read from the Identity service through its admin queries (servicedata/rpc.py).

Each role is a Django group holding these permissions:
- Super Admin: `view_site` + `edit_site` + `manage_employees`: everything, including the
  Employees pages where employees are added and given their role.
- Manager: `view_site` + `edit_site`. Day-to-day work: edit, modify, download.
- Monitor: `view_site`. Read-only monitoring.

Django superusers count as Super Admin. Employees with no role can sign in but every page answers 403.
"""

from django.contrib.auth.models import User
from django.db import models

SUPER_ADMIN = "Super Admin"
MANAGER = "Manager"
MONITOR = "Monitor"

# Role -> what it can do. Every employee has exactly one; this is the order shown on the employee form.
ROLES = {
    SUPER_ADMIN: "everything, including managing employees",
    MANAGER: "edit, modify and download data",
    MONITOR: "read-only monitoring",
}

VIEW_SITE = "accounts.view_site"
EDIT_SITE = "accounts.edit_site"
MANAGE_EMPLOYEES = "accounts.manage_employees"

PERMISSIONS = [
    ("view_site", "Can view the admin site"),
    ("edit_site", "Can edit, modify and download data"),
    ("manage_employees", "Can manage employees and their roles"),
]


class SitePermission(models.Model):
    """Holds the role permissions; there is no table behind it."""

    class Meta:
        """Unmanaged: only the permissions are created."""

        managed = False
        default_permissions = ()
        permissions = PERMISSIONS

    def __str__(self) -> str:
        """Never shown: the model exists only for its permissions."""
        return "site permissions"


class Employee(User):
    """An admin-site account. Same table as Django's auth user, named for what it is."""

    class Meta(
        User.Meta
    ):  # at runtime this is AbstractUser.Meta: only verbose names, no `swappable`
        proxy = True
        default_permissions = ()  # access comes from `manage_employees`
        verbose_name = "employee"
        verbose_name_plural = "employees"


def employee_role(employee: User) -> str | None:
    """The employee's role name. Superusers made with createsuperuser count as Super Admin."""
    role = next((g.name for g in employee.groups.all() if g.name in ROLES), None)
    return role or (SUPER_ADMIN if employee.is_superuser else None)


def email_verified(employee: User) -> bool:
    """Verified = the employee opened the emailed link and chose a password (accounts/views.py).
    Until then their password is unusable, so they cannot sign in."""
    return employee.has_usable_password()


class AccessLog(models.Model):
    """One request by a signed-in employee: who opened or changed what, and when.

    The pages show cross-tenant data, including decrypted names and emails, so every page an
    employee opens is recorded (accounts/middleware.py). `email` keeps the record readable after
    the employee's account is gone.
    ponytail: rows are never pruned; add a retention job when the table gets large.
    """

    employee = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="+")
    email = models.CharField(max_length=254)
    method = models.CharField(max_length=10)
    path = models.TextField(help_text="Full path with the query string, so searches are recorded.")
    status = models.PositiveSmallIntegerField()
    at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        """Newest first; no add/change/delete permissions: the log is written only by middleware."""

        default_permissions = ()
        ordering = ("-at",)

    def __str__(self) -> str:
        """`<email> <method> <path>` for shells and logs."""
        return f"{self.email} {self.method} {self.path}"
