from django.core.exceptions import ObjectDoesNotExist

from .models import UserNotification

def unread_notifications(request):
    unread_count = 0
    if request.user.is_authenticated:
        unread_count = UserNotification.objects.filter(recipient=request.user, is_seen=False).count()
    return {'unread_notifications_count': unread_count}


def nto_navigation(request):
    if not request.user.is_authenticated:
        return {'nto_entry_only': False}
    try:
        attempt = request.user.registrationpersonaldata
    except (AttributeError, ObjectDoesNotExist):
        return {'nto_entry_only': False}
    return {
        'nto_entry_only': bool(attempt.nto_campaign_slug),
    }
