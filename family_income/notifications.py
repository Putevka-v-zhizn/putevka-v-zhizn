from collections.abc import Iterable

from django.contrib.auth import get_user_model

from core.models import Notification, UserNotification


def create_family_income_notification(*, recipients: Iterable, sender, message: str):
    """Создаёт одно оповещение для всех получателей без дублирующих записей."""
    recipient_ids = {recipient.pk for recipient in recipients if recipient and recipient.pk}
    if not recipient_ids:
        return None

    notification = Notification.objects.create(sender=sender, message=message)
    UserNotification.objects.bulk_create([
        UserNotification(notification=notification, recipient_id=recipient_id)
        for recipient_id in recipient_ids
    ])
    return notification


def active_staff_users(*, exclude_user_id=None):
    users = get_user_model().objects.filter(is_staff=True, is_active=True)
    if exclude_user_id:
        users = users.exclude(pk=exclude_user_id)
    return users
