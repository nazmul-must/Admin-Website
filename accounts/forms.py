from django import forms
from django.contrib.auth.forms import AuthenticationForm, SetPasswordForm
from django.contrib.auth.models import Group
from django.db.models import Q

from .models import ROLES, SUPER_ADMIN, Employee, employee_role


class NotchedFieldsMixin:
    """Gives text-like inputs `placeholder=" "`, which the `.notched` CSS needs to float the label
    (design system §7.2). Render fields with templates/_field.html."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if getattr(field.widget, 'input_type', None) in ('text', 'email', 'password'):
                field.widget.attrs.setdefault('placeholder', ' ')


class LoginForm(NotchedFieldsMixin, AuthenticationForm):
    """Employees sign in with their email, which is stored as their username (see EmailIdentityMixin)."""

    error_messages = {
        **AuthenticationForm.error_messages,
        'invalid_login': 'Please enter a correct email and password. The password is case-sensitive.',
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].label = 'Email'
        self.fields['username'].widget.attrs['autocomplete'] = 'email'

    def clean_username(self):
        return self.cleaned_data['username'].strip().lower()


class PasswordForm(NotchedFieldsMixin, SetPasswordForm):
    pass


def role_field():
    """Required single choice: every employee has exactly one role."""
    return forms.ChoiceField(label='Role', choices=[(name, name) for name in ROLES], widget=forms.RadioSelect)


def set_role(employee, role):
    employee.groups.set([Group.objects.get(name=role)])


class EmailIdentityMixin:
    """Email is the employee's required, unique identity. It is stored lowercased and copied
    into `username`, so Django's standard login authenticates by email.

    A new address must be verified: the employee gets an unusable password and signs in only
    after opening the emailed link and choosing a password (accounts/views.py). After save,
    `needs_verification` tells the view to send that link."""

    needs_verification = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['email'].required = True
        self.fields['email'].label = 'Email'
        self.fields['email'].help_text = 'Used to sign in. A verification link is sent to it.'

    def email_changes_identity(self):
        return 'email' in self.changed_data

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        others = Employee.objects.exclude(pk=self.instance.pk)
        if others.filter(Q(email__iexact=email) | Q(username__iexact=email)).exists():
            raise forms.ValidationError('Another employee already uses this email.')
        return email

    def save(self, commit=True):
        employee = super().save(commit=False)
        employee.username = employee.email
        self.needs_verification = self.email_changes_identity()
        if self.needs_verification:
            employee.set_unusable_password()
        employee.save()
        set_role(employee, self.cleaned_data['role'])
        return employee


class EmployeeCreateForm(EmailIdentityMixin, NotchedFieldsMixin, forms.ModelForm):
    """No password here: the employee chooses one when they verify their email."""

    role = role_field()

    class Meta:
        model = Employee
        fields = ('email', 'first_name', 'last_name', 'role')


class EmployeeForm(EmailIdentityMixin, NotchedFieldsMixin, forms.ModelForm):
    role = role_field()

    class Meta:
        model = Employee
        fields = ('email', 'first_name', 'last_name', 'role', 'is_active')
        labels = {'is_active': 'Active'}
        help_texts = {'is_active': "Inactive employees can't sign in."}

    def __init__(self, *args, editor, **kwargs):
        super().__init__(*args, **kwargs)
        self.editor = editor
        self.fields['role'].initial = employee_role(self.instance)
        if self.is_self() and self.instance.email:
            # A changed address must be re-verified, which would sign the editor out mid-session.
            self.fields['email'].disabled = True
            self.fields['email'].help_text = 'Your own sign-in email. Another Super Admin can change it.'

    def is_self(self):
        return self.instance.pk == self.editor.pk

    def email_changes_identity(self):
        return super().email_changes_identity() and not self.is_self()

    def clean(self):
        cleaned = super().clean()
        # Stops a Super Admin locking themselves out of the Employees pages.
        if self.is_self() and (
            cleaned.get('role') != SUPER_ADMIN or not cleaned.get('is_active')
        ):
            raise forms.ValidationError("You can't remove your own Super Admin access. Ask another Super Admin.")
        return cleaned
