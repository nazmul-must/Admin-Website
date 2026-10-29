"""Route service-owned models to their service database, read-only.

The admin site must never write to a service database: writes bypass the
owning service's encryption, sagas, cache invalidation and RBAC sync.
A model opts in by setting `service_db` to a DATABASES alias.
"""

from django.conf import settings


class ServiceDatabaseRouter:
    def db_for_read(self, model, **hints):
        return getattr(model, 'service_db', None)

    def db_for_write(self, model, **hints):
        if getattr(model, 'service_db', None):
            raise PermissionError(f'{model.__name__} is read-only: it belongs to another service.')
        return None

    def allow_migrate(self, db, app_label, **hints):
        if db in settings.SERVICE_DATABASES or app_label == 'servicedata':
            return False
        return None
