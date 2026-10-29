"""Employees and their roles.

Employees are the people who sign in to this admin site. They are not Pro3AI users: those are
the customers of the product, read from the Identity service (servicedata.models.User).

Each role is a Django group holding these permissions:
- Super Admin: `view_site` + `edit_site` + `manage_employees`: everything, including the
  Employees pages where employees are added and given their role.
- Manager: `view_site` + `edit_site`. Day-to-day work: edit, modify, download.
- Monitor: `view_site`. Read-only monitoring.

Django superusers count as Super Admin. Employees with no role can sign in but every page answers 403.
"""

from django.contrib.auth.models import User
from django.db import models

SUPER_ADMIN = 'Super Admin'
MANAGER = 'Manager'
MONITOR = 'Monitor'

# Role -> what it can do. Every employee has exactly one; this is the order shown on the employee form.
ROLES = {
    SUPER_ADMIN: 'everything, including managing employees',
    MANAGER: 'edit, modify and download data',
    MONITOR: 'read-only monitoring',
}

VIEW_SITE = 'accounts.view_site'
EDIT_SITE = 'accounts.edit_site'
MANAGE_EMPLOYEES = 'accounts.manage_employees'

PERMISSIONS = [
    ('view_site', 'Can view the admin site'),
    ('edit_site', 'Can edit, modify and download data'),
    ('manage_employees', 'Can manage employees and their roles'),
]


class SitePermission(models.Model):
    """Holds the role permissions; there is no table behind it."""

    class Meta:
        managed = False
        default_permissions = ()
        permissions = PERMISSIONS


class Employee(User):
    """An admin-site account. Same table as Django's auth user, named for what it is."""

    class Meta(User.Meta):  # at runtime this is AbstractUser.Meta: only verbose names, no `swappable`
        proxy = True
        default_permissions = ()  # access comes from `manage_employees`
        verbose_name = 'employee'
        verbose_name_plural = 'employees'


def employee_role(employee):
    """The employee's role name. Superusers made with createsuperuser count as Super Admin."""
    role = next((g.name for g in employee.groups.all() if g.name in ROLES), None)
    return role or (SUPER_ADMIN if employee.is_superuser else None)


def email_verified(employee):
    """Verified = the employee opened the emailed link and chose a password (accounts/views.py).
    Until then their password is unusable, so they cannot sign in."""
    return employee.has_usable_password()
