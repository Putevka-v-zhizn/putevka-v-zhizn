from django.shortcuts import redirect

from core.services.programs import get_program_preferences, is_main_program_path


class ProgramSelectionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        user = request.user
        if not user.is_authenticated or user.is_staff or user.is_superuser:
            return None
        # Registration/authentication, staff and service endpoints retain their own gates.
        if request.path.startswith((
            "/register/", "/accounts/", "/programs/", "/admin/", "/staff/", "/internal/",
            "/static/", "/media/", "/before/", "/check-call-status/", "/redirect-registration/",
            "/change_phone_number/", "/return_telegram_connection/", "/telegram/",
        )):
            return None
        try:
            attempt = user.registrationpersonaldata
        except AttributeError:
            attempt = None
        if attempt and attempt.current_step != "finish":
            return redirect("redirect_to_current_step")
        preferences = get_program_preferences(user)
        if not preferences.active_program:
            return redirect("programs")
        if request.resolver_match.app_name == "nto_travel" and request.resolver_match.url_name != "landing" and not preferences.nto_enabled:
            return redirect("programs")
        if is_main_program_path(request.path) and not preferences.main_enabled:
            return redirect("programs")
        return None
