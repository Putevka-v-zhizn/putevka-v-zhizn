from unittest.mock import patch

from django.core.exceptions import PermissionDenied, SuspiciousOperation
from django.http import HttpResponse
from django.test import Client, SimpleTestCase, override_settings
from django.urls import path

from Putevka.urls import handler400, handler403, handler404, handler500


def failing_view(request, kind):
    errors = {"400": SuspiciousOperation, "403": PermissionDenied, "500": RuntimeError}
    raise errors[kind]("private-error-details")


def form_view(request):
    return HttpResponse("form")


urlpatterns = [
    path("fail/<str:kind>/", failing_view),
    path("form/", form_view),
]


@override_settings(DEBUG=False, ROOT_URLCONF=__name__, ALLOWED_HOSTS=["testserver"])
class ErrorPageTests(SimpleTestCase):
    # SimpleTestCase forbids database queries, including in error templates.
    def setUp(self):
        # Keep test exceptions out of the production notification queue.
        notifications = patch("core.telegram_tasks.enqueue_admin_message")
        notifications.start()
        self.addCleanup(notifications.stop)

    def test_error_responses(self):
        client = Client(raise_request_exception=False)
        for status, title in ((400, "Не удалось обработать запрос"),
                              (403, "Доступ ограничен"),
                              (404, "Страница не найдена"),
                              (500, "Не удалось загрузить страницу")):
            with self.subTest(status=status), patch(
                "core.context_processors.unread_notifications",
                side_effect=AssertionError("Error page must not run context processors"),
            ):
                response = client.get("/missing/" if status == 404 else f"/fail/{status}/")
                self.assertContains(response, title, status_code=status)
                self.assertContains(response, 'href="/"', status_code=status)
                self.assertNotContains(response, "private-error-details", status_code=status)
                self.assertNotContains(response, "Traceback", status_code=status)

    def test_csrf_failure(self):
        client = Client(enforce_csrf_checks=True)
        response = client.post("/form/", {"value": "test"})
        self.assertContains(response, "Не удалось отправить форму", status_code=403)
        self.assertContains(response, "обновите её", status_code=403)
        self.assertNotContains(response, "CSRF cookie", status_code=403)

    def test_server_error_is_logged(self):
        with self.assertLogs("django.request", level="ERROR") as logs:
            response = Client(raise_request_exception=False).get("/fail/500/")
        self.assertEqual(response.status_code, 500)
        self.assertTrue(any(record.exc_info for record in logs.records))
