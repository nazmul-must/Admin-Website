"""Sign-in, password and employee forms."""

from typing import Any

from django import forms
from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.auth.forms import AuthenticationForm, SetPasswordForm
from django.contrib.auth.models import AnonymousUser, Group
from django.db.models import Q

from . import throttle
from .models import ROLES, SUPER_ADMIN, Employee, employee_role


class NotchedFieldsMixin:
    """Gives text-like inputs `placeholder=" "`, which the `.notched` CSS needs to float the label
    (design system §7.2). Render fields with templates/_field.html."""

    fields: dict[str, forms.Field]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Set the placeholder on every text, email and password input."""
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if getattr(field.widget, "input_type", None) in ("text", "email", "password"):
                field.widget.attrs.setdefault("placeholder", " ")


class LoginForm(NotchedFieldsMixin, AuthenticationForm):
    """Employees sign in with their email, which is stored as their username (see
    EmployeeFormBase). Repeated failures lock the email for a while (accounts/throttle.py)."""

    error_messages = {
        **AuthenticationForm.error_messages,
        "invalid_login": "Please enter a correct email and password. The password is case-sensitive.",
        "locked": (
            f"Too many failed sign-ins for this email. "
            f"Try again in {throttle.LOCKOUT_SECONDS // 60} minutes."
        ),
    }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Label the username field as the email it holds."""
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "Email"
        self.fields["username"].widget.attrs["autocomplete"] = "email"

    def clean_username(self) -> str:
        """Emails are stored lowercased."""
        return self.cleaned_data["username"].strip().lower()

    def clean(self) -> dict[str, Any]:
        """Refuse a locked email before checking the password; count failures; reset on success."""
        email = self.cleaned_data.get("username")
        if email and throttle.is_locked(email):
            raise forms.ValidationError(self.error_messages["locked"], code="locked")
        try:
            cleaned = super().clean() or {}
        except forms.ValidationError:
            if email:
                throttle.record_failure(email)
            raise
        if email:
            throttle.clear(email)
        return cleaned


class PasswordForm(NotchedFieldsMixin, SetPasswordForm):
    """Choosing a password on the emailed sign-in link page."""


def role_field() -> forms.ChoiceField:
    """Required single choice: every employee has exactly one role."""
    choices = [(name, name) for name in ROLES]
    return forms.ChoiceField(label="Role", choices=choices, widget=forms.RadioSelect)


def set_role(employee: Employee, role: str) -> None:
    """Make `role` the employee's only role group."""
    employee.groups.set([Group.objects.get(name=role)])


class EmployeeFormBase(NotchedFieldsMixin, forms.ModelForm):
    """Email is the employee's required, unique identity. It is stored lowercased and copied
    into `username`, so Django's standard login authenticates by email.

    A new address must be verified: the employee gets an unusable password and signs in only
    after opening the emailed link and choosing a password (accounts/views.py). After save,
    `needs_verification` tells the view to send that link. The role is saved with the
    many-to-many data, so `save(commit=False)` defers it to `save_m2m()` as Django does."""

    instance: Employee
    needs_verification = False
    role = role_field()

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Make email required and explain what it is for."""
        super().__init__(*args, **kwargs)
        self.fields["email"].required = True
        self.fields["email"].label = "Email"
        self.fields["email"].help_text = "Used to sign in. A verification link is sent to it."

    def email_changes_identity(self) -> bool:
        """Whether this save gives the employee a new sign-in address to verify."""
        return "email" in self.changed_data

    def clean_email(self) -> str:
        """Lowercase the email and refuse one another employee already signs in with."""
        email = self.cleaned_data["email"].strip().lower()
        others = Employee.objects.exclude(pk=self.instance.pk)
        if others.filter(Q(email__iexact=email) | Q(username__iexact=email)).exists():
            raise forms.ValidationError("Another employee already uses this email.")
        return email

    def save(self, commit: bool = True) -> Employee:
        """Copy the email into the username, require verification for a new address, and save
        the role with the many-to-many data (so after `commit=False`, on `save_m2m()`)."""
        employee = self.instance
        employee.username = employee.email
        self.needs_verification = self.email_changes_identity()
        if self.needs_verification:
            employee.set_unusable_password()
        employee = super().save(commit)
        role = self.cleaned_data["role"]
        if commit:
            set_role(employee, role)
            return employee
        save_m2m = self.save_m2m

        def save_m2m_and_role() -> None:
            save_m2m()
            set_role(employee, role)

        self.save_m2m = save_m2m_and_role
        return employee


class EmployeeCreateForm(EmployeeFormBase):
    """No password here: the employee chooses one when they verify their email."""

    class Meta:
        """Fields a Super Admin fills in for a new employee."""

        model = Employee
        fields = ("email", "first_name", "last_name", "role")


class EmployeeForm(EmployeeFormBase):
    """Edit an employee: name, email, role and whether they can sign in."""

    class Meta:
        """Fields a Super Admin edits; `is_active` is shown as Active."""

        model = Employee
        fields = ("email", "first_name", "last_name", "role", "is_active")
        labels = {"is_active": "Active"}
        help_texts = {"is_active": "Inactive employees can't sign in."}

    def __init__(self, *args: Any, editor: AbstractBaseUser | AnonymousUser, **kwargs: Any) -> None:
        """`editor` is the signed-in Super Admin; editing themselves limits what they can change."""
        super().__init__(*args, **kwargs)
        self.editor = editor
        self.fields["role"].initial = employee_role(self.instance)
        if self.is_self() and self.instance.email:
            # A changed address must be re-verified, which would sign the editor out mid-session.
            self.fields["email"].disabled = True
            self.fields[
                "email"
            ].help_text = "Your own sign-in email. Another Super Admin can change it."

    def is_self(self) -> bool:
        """Whether the editor is editing their own account."""
        return self.instance.pk == self.editor.pk

    def email_changes_identity(self) -> bool:
        """Editors can't change their own email here, so only others' changes need verifying."""
        return super().email_changes_identity() and not self.is_self()

    def clean(self) -> dict[str, Any]:
        """Stop a Super Admin locking themselves out of the Employees pages."""
        cleaned = super().clean() or {}
        if self.is_self() and (cleaned.get("role") != SUPER_ADMIN or not cleaned.get("is_active")):
            raise forms.ValidationError(
                "You can't remove your own Super Admin access. Ask another Super Admin."
            )
        return cleaned
