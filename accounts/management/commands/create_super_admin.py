"""`create_super_admin`: the first employee, who signs in without email verification."""

import getpass
from argparse import ArgumentParser

from django.contrib.auth.models import Group
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email
from django.db.models import Q

from accounts.models import SUPER_ADMIN, Employee


class Command(BaseCommand):
    """Create (or finish) a Super Admin with an email and a password typed at the prompt."""

    help = (
        "Create a Super Admin who signs in straight away with email and password, without email "
        "verification. Use it for the first employee; Super Admins invite everyone else from the "
        "Employees page, and those employees verify their email."
    )

    def add_arguments(self, parser: ArgumentParser) -> None:
        """`--email`; asked for when omitted."""
        parser.add_argument("--email", help="Asked for when omitted.")

    def handle(self, *_args: object, email: str | None = None, **_options: object) -> None:
        """Validate the email and password, then save the employee as a Super Admin."""
        email = (email or input("Email: ")).strip().lower()
        try:
            validate_email(email)
        except ValidationError as exc:
            raise CommandError(f"Not an email address: {email}") from exc
        employee = Employee.objects.filter(
            Q(email__iexact=email) | Q(username__iexact=email)
        ).first()
        if employee and employee.has_usable_password():
            raise CommandError(f"{email} is already an employee with a password.")
        # An invited employee who never verified is finished here instead of refused.
        employee = employee or Employee(username=email, email=email)
        while True:
            password = getpass.getpass("Password: ")
            if password != getpass.getpass("Password (again): "):
                self.stderr.write("Passwords don't match. Try again.")
                continue
            try:
                validate_password(password, employee)
                break
            except ValidationError as exc:
                self.stderr.write("\n".join(exc.messages))

        employee.set_password(password)
        employee.save()
        employee.groups.set([Group.objects.get(name=SUPER_ADMIN)])
        self.stdout.write(
            self.style.SUCCESS(f"{email} is a Super Admin. Sign in at /login/ with this email.")
        )
