"""Employees and their roles.

Employees are the people who sign in to this admin site. They are not Pro3AI users: those are
the customers of the product, read from the Identity service (servicedata.models.User).

Each role is a Django group holding these permissions:
- Super Admin: `view_site` + `edit_site` + `manage_employees`, plus the Employee admin
  permissions, so its members add employees and assign roles at /admin/ (Employees).
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
        verbose_name = 'employee'
        verbose_name_plural = 'employees'
