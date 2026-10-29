from django import forms
from django.contrib.auth.forms import AuthenticationForm, SetPasswordForm, UserCreationForm
from django.contrib.auth.models import Group

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
    pass


class PasswordForm(NotchedFieldsMixin, SetPasswordForm):
    pass


def role_field():
    """Required single choice: every employee has exactly one role."""
    return forms.ChoiceField(label='Role', choices=[(name, name) for name in ROLES], widget=forms.RadioSelect)


def set_role(employee, role):
    employee.groups.set([Group.objects.get(name=role)])


class EmployeeCreateForm(NotchedFieldsMixin, UserCreationForm):
    role = role_field()
    field_order = ['username', 'first_name', 'last_name', 'email', 'role', 'password1', 'password2']

    class Meta(UserCreationForm.Meta):
        model = Employee
        fields = ('username', 'first_name', 'last_name', 'email')

    def save(self, commit=True):
        employee = super().save(commit=True)
        set_role(employee, self.cleaned_data['role'])
        return employee


class EmployeeForm(NotchedFieldsMixin, forms.ModelForm):
    role = role_field()

    class Meta:
        model = Employee
        fields = ('username', 'first_name', 'last_name', 'email', 'role', 'is_active')
        labels = {'is_active': 'Active'}
        help_texts = {'is_active': "Inactive employees can't sign in."}

    def __init__(self, *args, editor, **kwargs):
        super().__init__(*args, **kwargs)
        self.editor = editor
        self.fields['role'].initial = employee_role(self.instance)

    def clean(self):
        cleaned = super().clean()
        # Stops a Super Admin locking themselves out of the Employees pages.
        if self.instance.pk == self.editor.pk and (
            cleaned.get('role') != SUPER_ADMIN or not cleaned.get('is_active')
        ):
            raise forms.ValidationError("You can't remove your own Super Admin access. Ask another Super Admin.")
        return cleaned

    def save(self, commit=True):
        employee = super().save(commit=True)
        set_role(employee, self.cleaned_data['role'])
        return employee
