import logging
from smtplib import SMTPException

from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.views import PasswordResetConfirmView
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.views.decorators.http import require_POST

from .decorators import role_required
from .forms import EmployeeCreateForm, EmployeeForm, PasswordForm
from .invites import email_sign_in_link
from .models import MANAGE_EMPLOYEES, ROLES, Employee, email_verified, employee_role

logger = logging.getLogger(__name__)
manage_required = role_required(MANAGE_EMPLOYEES)


def send_sign_in_link(request, employee):
    try:
        email_sign_in_link(employee, request.build_absolute_uri('/'))
    except (SMTPException, OSError):
        logger.exception('Could not email %s', employee.email)
        messages.error(request, f'Could not send the email to {employee.email}. Try "Resend" later.')
        return
    kind = 'Password reset' if email_verified(employee) else 'Verification'
    messages.success(request, f'{kind} email sent to {employee.email}.')


@manage_required
def employee_list(request):
    employees = Employee.objects.prefetch_related('groups').order_by('email', 'username')
    rows = [(e, employee_role(e), email_verified(e)) for e in employees]
    return render(request, 'accounts/employee_list.html', {'rows': rows})


@manage_required
def employee_add(request):
    form = EmployeeCreateForm(request.POST or None)
    if form.is_valid():
        employee = form.save()
        messages.success(request, f'{employee.email} added as {form.cleaned_data["role"]}.')
        send_sign_in_link(request, employee)
        return redirect('employee-list')
    return render(request, 'accounts/employee_form.html', {
        'form': form, 'title': 'Add Employee', 'roles': ROLES, 'back_url': reverse('employee-list'),
        'blurb': 'They get an email with a link to verify their address and choose a password.',
        'submit': 'Add and Send Invite',
    })


@manage_required
def employee_edit(request, pk):
    employee = get_object_or_404(Employee, pk=pk)
    form = EmployeeForm(request.POST or None, instance=employee, editor=request.user)
    if form.is_valid():
        form.save()
        messages.success(request, f'{employee.email} saved.')
        if form.needs_verification:
            send_sign_in_link(request, employee)
        return redirect('employee-list')
    return render(request, 'accounts/employee_form.html', {
        'form': form, 'employee': employee, 'verified': email_verified(employee), 'roles': ROLES,
        'title': employee.get_full_name() or employee.email or employee.username,
        'blurb': f'Signs in with {employee.email}.' if employee.email else 'Add an email: it becomes the sign-in.',
        'submit': 'Save Changes', 'back_url': reverse('employee-list'),
    })


@require_POST
@manage_required
def employee_send_link(request, pk):
    employee = get_object_or_404(Employee, pk=pk)
    send_sign_in_link(request, employee)
    return redirect('employee-edit', pk=pk)


class VerifyEmailView(PasswordResetConfirmView):
    """Public page behind the emailed link: choosing a password verifies the email."""

    template_name = 'accounts/verify.html'
    form_class = PasswordForm
    success_url = reverse_lazy('login')

    def form_valid(self, form):
        response = super().form_valid(form)
        if self.request.user.pk == form.user.pk:  # signed in already: keep the session valid
            update_session_auth_hash(self.request, form.user)
        messages.success(self.request, f'Email verified and password set. Sign in with {form.user.email}.')
        return response
