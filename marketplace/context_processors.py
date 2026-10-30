from django.db.models import Q
from .models import Message


def activity_counts(request):
    if not request.user.is_authenticated:
        return {}
    return {
        'unread_notifications': request.user.notifications.filter(is_read=False).count(),
        'unread_messages': Message.objects.filter(
            Q(conversation__participant_a=request.user) | Q(conversation__participant_b=request.user),
            is_read=False,
        ).exclude(sender=request.user).count(),
    }
