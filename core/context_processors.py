from .models import UserNotification
from .services.programs import get_program_preferences, request_program

def unread_notifications(request):
    unread_count = 0
    if request.user.is_authenticated:
        unread_count = UserNotification.objects.filter(recipient=request.user, is_seen=False).count()
    return {'unread_notifications_count': unread_count}


def nto_navigation(request):
    if not request.user.is_authenticated or request.user.is_staff or request.user.is_superuser:
        return {'nto_entry_only': False, 'show_program_navigation': False}
    preferences = get_program_preferences(request.user)
    current = request_program(request, preferences)
    return {
        'nto_entry_only': current == 'nto',
        'show_program_navigation': bool(current),
        'current_program': current,
        'both_programs': preferences.main_enabled and preferences.nto_enabled,
        'program_preferences': preferences,
    }
