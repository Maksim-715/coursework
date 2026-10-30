from datetime import timedelta
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.http import Http404
from django.urls import reverse
from django.utils import timezone
from .models import Interview, InterviewEvent, User
from .services import notify


def participants(user):
    return Q(company__owner=user) | Q(worker=user)


def announce(item, recipient, title):
    notify(recipient, title, f'{item.title} · {timezone.localtime(item.starts_at):%d.%m.%Y %H:%M}', reverse('interview_detail', args=[item.pk]))


@transaction.atomic
def schedule(item, actor):
    # Both participant rows are locked in stable order to serialize concurrent scheduling.
    list(User.objects.select_for_update().filter(pk__in=[actor.pk, item.worker_id]).order_by('pk'))
    original = None
    if item.pk:
        original = Interview.objects.select_for_update().get(pk=item.pk)
        if not original.is_active:
            raise ValidationError('Перенос доступен только для активных собеседований.')
    if item.starts_at <= timezone.now():
        raise ValidationError('Выберите время в будущем.')
    conflicts = Interview.objects.filter(
        Q(company__owner_id=actor.pk) | Q(worker_id=item.worker_id),
        status__in=['pending', 'confirmed'], starts_at__lt=item.ends_at,
        starts_at__gt=item.starts_at - timedelta(minutes=240),
    ).exclude(pk=item.pk).select_related('company')
    if any(other.ends_at > item.starts_at for other in conflicts):
        raise ValidationError('У одного из участников уже есть собеседование в это время.')
    if original and all(getattr(original, field) == getattr(item, field) for field in
                        ['title', 'vacancy_id', 'starts_at', 'duration', 'format', 'location', 'meeting_url', 'description']):
        return original
    item.full_clean()
    item.status = Interview.Status.PENDING
    item.save()
    detail = f'{timezone.localtime(item.starts_at):%d.%m.%Y %H:%M} · {item.duration} мин · {item.get_format_display()}'
    if original:
        detail = f'Ранее: {timezone.localtime(original.starts_at):%d.%m.%Y %H:%M}. Теперь: ' + detail
    InterviewEvent.objects.create(interview=item, actor=actor, title='Условия встречи изменены' if original else 'Встреча назначена', detail=detail)
    announce(item, item.worker_id, 'Собеседование: подтвердите дату и время')
    return item


@transaction.atomic
def transition(user, pk, target, result='', reason=''):
    item = Interview.objects.select_for_update().select_related('company').filter(participants(user), pk=pk).first()
    if not item:
        raise Http404
    employer = item.company.owner_id == user.pk
    allowed = {'pending': ['cancelled'], 'confirmed': ['cancelled', 'completed']} if employer else {'pending': ['confirmed', 'declined', 'cancelled'], 'confirmed': ['cancelled']}
    if target not in allowed.get(item.status, []):
        raise ValidationError('Этот переход статуса недоступен.')
    if target == 'confirmed' and item.starts_at <= timezone.now():
        raise ValidationError('Нельзя подтвердить прошедшее собеседование.')
    if target == 'completed':
        if item.ends_at > timezone.now():
            raise ValidationError('Подведите итоги после окончания собеседования.')
        if not result.strip():
            raise ValidationError('Укажите итоги собеседования.')
        item.result = result.strip()
    if len(reason) > 2000:
        raise ValidationError('Причина должна содержать не более 2000 символов.')
    item.status = target
    item.save(update_fields=['status', 'result'])
    InterviewEvent.objects.create(interview=item, actor=user, title=item.get_status_display(), detail=reason.strip() if target in ['cancelled', 'declined'] else item.result if target == 'completed' else '')
    announce(item, item.worker_id if employer else item.company.owner_id, f'Собеседование: {item.get_status_display()}')
    return item
