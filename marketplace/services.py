"""Transactional business operations shared by web views."""
from collections import defaultdict
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from .models import (User, Order, Rental, StaffOffer, Availability, Notification,
                     Application, Invitation, Vacancy)


def notify(recipient_id, title, text='', url=None):
    return Notification.objects.create(
        recipient_id=recipient_id, title=title[:200], text=text,
        url=url or reverse('dashboard'),
    )


def peak_reserved(offer, start, end, exclude=None):
    """Peak simultaneous reservations, with both boundaries inclusive."""
    events = defaultdict(int)
    rentals = Rental.objects.filter(
        offer=offer, status=Rental.Status.ACCEPTED, start__lte=end, end__gte=start,
    ).exclude(pk=exclude)
    for rental in rentals:
        events[max(rental.start, start).toordinal()] += rental.count
        events[min(rental.end, end).toordinal() + 1] -= rental.count
    occupied = peak = 0
    for day in sorted(events):
        occupied += events[day]
        peak = max(peak, occupied)
    return peak


@transaction.atomic
def move_order(actor, pk, target):
    initial = get_object_or_404(Order.objects.select_related('service'), pk=pk)
    if actor.pk not in (initial.customer_id, initial.service.owner_id):
        from django.http import Http404
        raise Http404
    # One lock for all services of this worker prevents double-booking across services.
    User.objects.select_for_update().get(pk=initial.service.owner_id)
    order = Order.objects.select_for_update().select_related('service').get(pk=pk)
    if actor.pk == order.customer_id:
        if target != 'cancelled':
            from django.http import Http404
            raise Http404
        valid = target == 'cancelled' and order.status in ['new', 'accepted']
        recipient = order.service.owner_id
    else:
        transitions = {'new': ['accepted', 'rejected'], 'accepted': ['working'], 'working': ['done']}
        valid = target in transitions.get(order.status, [])
        recipient = order.customer_id
    if not valid:
        raise ValidationError('Этот переход статуса недоступен. Обновите страницу.')
    if target == 'accepted':
        if order.date < timezone.localdate():
            raise ValidationError('Нельзя подтвердить заказ на прошедшую дату.')
        if Availability.objects.filter(worker_id=order.service.owner_id, date=order.date, available=False).exists():
            raise ValidationError('В календаре на эту дату отмечена занятость.')
        if Order.objects.filter(service__owner_id=order.service.owner_id, date=order.date, status__in=['accepted', 'working']).exclude(pk=pk).exists():
            raise ValidationError('На эту дату уже есть подтверждённый заказ.')
    order.status = target
    order.save(update_fields=['status'])
    notify(recipient, f'Заказ: {order.get_status_display()}', f'{order.service.title} · {order.date:%d.%m.%Y}', reverse('dashboard') + f'#order-{order.pk}')
    return order


@transaction.atomic
def move_rental(actor, pk, target):
    initial = get_object_or_404(Rental.objects.select_related('offer__company', 'customer'), pk=pk)
    owner_id = initial.offer.company.owner_id
    customer_id = initial.customer.owner_id
    if actor.pk not in (owner_id, customer_id):
        from django.http import Http404
        raise Http404
    offer = StaffOffer.objects.select_for_update().get(pk=initial.offer_id)
    rental = Rental.objects.select_for_update().get(pk=pk)
    if actor.pk == customer_id:
        valid = target == 'cancelled' and rental.status in ['new', 'accepted'] and rental.start >= timezone.localdate()
        recipient = owner_id
    else:
        valid = rental.status == 'new' and target in ['accepted', 'rejected']
        recipient = customer_id
    if not valid:
        raise ValidationError('Этот переход статуса недоступен. Подтверждённые заявки нельзя переоткрыть.')
    if target == 'accepted':
        if rental.start < timezone.localdate() or not (offer.start <= rental.start <= rental.end <= offer.end):
            raise ValidationError('Срок заявки больше не соответствует предложению.')
        if peak_reserved(offer, rental.start, rental.end, exclude=pk) + rental.count > offer.count:
            raise ValidationError('На эти даты недостаточно свободных сотрудников.')
    rental.status = target
    rental.save(update_fields=['status'])
    notify(recipient, f'Аренда: {rental.get_status_display()}', f'{offer.specialty} · {rental.count} чел.', reverse('dashboard') + ('#rentals-in' if recipient == owner_id else '#rentals-out'))
    return rental


@transaction.atomic
def move_application(actor, pk, target):
    initial = get_object_or_404(Application.objects.select_related('vacancy__company'), pk=pk)
    if actor.pk not in (initial.worker_id, initial.vacancy.company.owner_id):
        from django.http import Http404
        raise Http404
    # Submission/reactivation locks the vacancy first as well.
    vacancy = Vacancy.objects.select_for_update().get(pk=initial.vacancy_id)
    application = Application.objects.select_for_update().get(pk=pk)
    application.vacancy = vacancy
    if actor.pk == application.worker_id:
        valid = target == 'withdrawn' and application.status in ['review', 'invited']
        recipient = application.vacancy.company.owner_id
    elif actor.pk == application.vacancy.company.owner_id:
        valid = target in ['review', 'invited', 'rejected', 'hired'] and application.status not in ['withdrawn', 'hired']
        recipient = application.worker_id
    else:
        from django.http import Http404
        raise Http404
    if not valid:
        raise ValidationError('Этот отклик больше нельзя перевести в выбранный статус.')
    if application.status == target:
        return application
    application.status = target
    application.save(update_fields=['status'])
    notify(recipient, f'Отклик: {application.get_status_display()}', application.vacancy.title, reverse('dashboard') + f'#application-{application.pk}')
    return application


@transaction.atomic
def respond_invitation(actor, pk, target):
    invitation = get_object_or_404(Invitation.objects.select_for_update().select_related('company'), pk=pk, worker=actor)
    if invitation.status != 'new' or target not in ['accepted', 'declined']:
        raise ValidationError('На это приглашение уже дан ответ.')
    invitation.status = target
    invitation.save(update_fields=['status'])
    notify(invitation.company.owner_id, f'Приглашение: {invitation.get_status_display()}', str(actor), reverse('dashboard') + '#invitations')
    return invitation
