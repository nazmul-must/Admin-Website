from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from .decorators import role_required
from .forms import EmployeeCreateForm, EmployeeForm, PasswordForm
from .models import MANAGE_EMPLOYEES, ROLES, Employee, employee_role

manage_required = role_required(MANAGE_EMPLOYEES)


@manage_required
def employee_list(request):
    employees = Employee.objects.prefetch_related('groups').order_by('username')
    return render(request, 'accounts/employee_list.html', {'rows': [(e, employee_role(e)) for e in employees]})


@manage_required
def employee_add(request):
    form = EmployeeCreateForm(request.POST or None)
    if form.is_valid():
        employee = form.save()
        messages.success(request, f'{employee.username} added as {form.cleaned_data["role"]}.')
        return redirect('employee-list')
    return render(request, 'accounts/employee_form.html', {
        'form': form, 'title': 'Add Employee', 'blurb': 'Create an account for someone who will use this admin site.',
        'submit': 'Add Employee', 'roles': ROLES, 'back_url': reverse('employee-list'),
    })


@manage_required
def employee_edit(request, pk):
    employee = get_object_or_404(Employee, pk=pk)
    form = EmployeeForm(request.POST or None, instance=employee, editor=request.user)
    if form.is_valid():
        form.save()
        messages.success(request, f'{employee.username} saved.')
        return redirect('employee-list')
    return render(request, 'accounts/employee_form.html', {
        'form': form, 'employee': employee, 'title': employee.get_full_name() or employee.username,
        'blurb': f'Signs in as {employee.username}.', 'submit': 'Save Changes', 'roles': ROLES,
        'back_url': reverse('employee-list'), 'password_url': reverse('employee-password', args=[pk]),
    })


@manage_required
def employee_password(request, pk):
    employee = get_object_or_404(Employee, pk=pk)
    form = PasswordForm(employee, request.POST or None)
    if form.is_valid():
        form.save()
        if employee.pk == request.user.pk:
            update_session_auth_hash(request, employee)  # stay signed in after changing your own password
        messages.success(request, f'Password changed for {employee.username}.')
        return redirect('employee-edit', pk=pk)
    return render(request, 'accounts/employee_form.html', {
        'form': form, 'employee': employee, 'title': 'Set Password',
        'blurb': f'Choose a new password for {employee.username}. Tell them over a secure channel.',
        'submit': 'Set Password', 'back_url': reverse('employee-edit', args=[pk]),
    })
