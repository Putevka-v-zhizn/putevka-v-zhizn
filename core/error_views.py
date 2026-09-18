"""Error responses that do not depend on database or request context processors."""

from django.http import HttpResponse
from django.template.loader import render_to_string


def _error_response(status, title, message):
    content = render_to_string("errors/base.html", {
        "status": status, "title": title, "message": message,
    })
    return HttpResponse(content, status=status)


def bad_request(request, exception):
    return _error_response(400, "Не удалось обработать запрос",
                           "Проверьте адрес страницы или перейдите на главную.")


def permission_denied(request, exception):
    return _error_response(403, "Доступ ограничен",
                           "У вас нет доступа к этой странице.")


def page_not_found(request, exception):
    return _error_response(404, "Страница не найдена",
                           "Возможно, адрес изменился или страница была удалена.")


def server_error(request):
    return _error_response(500, "Не удалось загрузить страницу",
                           "На сервере произошла ошибка. Попробуйте зайти позже.")


def csrf_failure(request, reason=""):
    return _error_response(403, "Не удалось отправить форму",
                           "Вернитесь на исходную страницу, обновите её и отправьте форму заново.")
