"""/admin/ is the Employees area: Super Admins add employees and assign their roles here."""

from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import AdminUserCreationForm, AuthenticationForm, UserChangeForm
from django.contrib.auth.models import Group, User

from .models import MANAGE_EMPLOYEES, ROLES, SUPER_ADMIN, Employee

admin.site.site_header = admin.site.site_title = 'Pro3AI Admin'
admin.site.index_title = 'Employees'
# Access follows the Super Admin role, not Django's is_staff flag, and uses the site's styled login.
admin.site.login_template = 'registration/login.html'
admin.site.login_form = AuthenticationForm
admin.site.has_permission = lambda request: request.user.is_active and request.user.has_perm(MANAGE_EMPLOYEES)

# Employees replace Django's "Users" (that word means Pro3AI customers here). Roles are fixed
# by the accounts migration, so they are chosen on the employee form, never edited.
admin.site.unregister(User)
admin.site.unregister(Group)


def employee_role(employee):
    """The employee's role name. Superusers made with createsuperuser count as Super Admin."""
    role = next((g.name for g in employee.groups.all() if g.name in ROLES), None)
    return role or (SUPER_ADMIN if employee.is_superuser else None)


def role_field():
    """Required single choice: every employee has exactly one role."""
    return forms.ChoiceField(
        label='Role', choices=[(name, f'{name}: {does}') for name, does in ROLES.items()], widget=forms.RadioSelect)


class EmployeeCreationForm(AdminUserCreationForm):
    role = role_field()


class EmployeeChangeForm(UserChangeForm):
    role = role_field()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['role'].initial = employee_role(self.instance)


@admin.register(Employee)
class EmployeeAdmin(UserAdmin):
    form = EmployeeChangeForm
    add_form = EmployeeCreationForm
    list_display = ('username', 'email', 'first_name', 'last_name', 'current_role', 'is_active', 'last_login')
    list_filter = ('is_active',)
    # No is_staff / is_superuser / per-employee permissions: access comes from the role only.
    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ('Personal info', {'fields': ('first_name', 'last_name', 'email')}),
        ('Access', {'fields': ('role', 'is_active')}),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
    )
    add_fieldsets = (
        (None, {'classes': ('wide',), 'fields': ('username', 'usable_password', 'password1', 'password2', 'role')}),
    )

    @admin.display(description='Role')
    def current_role(self, obj):
        return employee_role(obj) or '—'

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related('groups')

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        obj.groups.set([Group.objects.get(name=form.cleaned_data['role'])])
