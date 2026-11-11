"""Tests for the project-level pieces: the health endpoint and the JSON log format."""

import json
import logging
from unittest import mock

from django.db import DatabaseError
from django.test import TestCase

from admin.log_format import JsonFormatter


class HealthTests(TestCase):
    """/health/ is public and reports only the site's own database."""

    def test_ok_without_sign_in(self) -> None:
        response = self.client.get("/health/")
        self.assertEqual((response.status_code, response.json()), (200, {"status": "ok"}))

    def test_database_down_is_503(self) -> None:
        with (
            mock.patch("admin.health.connection.ensure_connection", side_effect=DatabaseError),
            self.assertLogs("admin.health", logging.ERROR),
        ):
            response = self.client.get("/health/")
        self.assertEqual(response.status_code, 503)


class JsonFormatterTests(TestCase):
    """PROD log lines are single JSON objects with the services' field names."""

    def test_fields(self) -> None:
        record = logging.LogRecord("x.y", logging.WARNING, __file__, 1, "hi %s", ("there",), None)
        line = json.loads(JsonFormatter().format(record))
        self.assertEqual(
            {k: line[k] for k in ("level", "logger", "message")},
            {"level": "WARNING", "logger": "x.y", "message": "hi there"},
        )
