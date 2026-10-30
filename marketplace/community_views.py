from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, OuterRef, Q, Subquery
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .forms import AccountForm, MessageForm
from .models import Favorite, Notification, Conversation, Message, Order, Rental, Application, Invitation, Interview
from .selectors import get_listing, FAVORITE_FIELDS
from .services import notify


@login_required
def account(request):
    form = AccountForm(request.POST or None, instance=request.user)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Данные аккаунта обновлены.')
        return redirect('account')
    return render(request, 'marketplace/account.html', {'form': form})


@login_required
@require_POST
def favorite_toggle(request, kind, pk):
    obj = get_listing(request.user, kind, pk)
    favorite, created = Favorite.objects.get_or_create(user=request.user, **{FAVORITE_FIELDS[kind]: obj})
    if not created:
        favorite.delete()
    messages.success(request, 'Добавлено в избранное.' if created else 'Удалено из избранного.')
    return redirect('detail', kind=kind, pk=pk)


@login_required
def favorites(request):
    queryset = Favorite.objects.filter(user=request.user).select_related('vacancy__company', 'service__owner', 'staff__company', 'resume__owner')
    selected = request.GET.get('kind', '')
    if selected in FAVORITE_FIELDS:
        queryset = queryset.filter(**{f'{FAVORITE_FIELDS[selected]}__isnull': False})
    page = Paginator(queryset, 12).get_page(request.GET.get('page'))
    for favorite in page:
        target = favorite.target
        # A hidden resume must disappear from saved lists as well as search.
        try:
            get_listing(request.user, favorite.kind, target.pk)
            favorite.can_view = True
        except (Http404, PermissionDenied):
            favorite.can_view = False
    return render(request, 'marketplace/favorites.html', {'items': page, 'selected_kind': selected})


@login_required
@require_POST
def favorite_remove(request, pk):
    get_object_or_404(Favorite, user=request.user, pk=pk).delete()
    return redirect('favorites')


@login_required
def notifications(request):
    queryset = Notification.objects.filter(recipient=request.user)
    if request.GET.get('unread') == '1':
        queryset = queryset.filter(is_read=False)
    return render(request, 'marketplace/notifications.html', {'items': Paginator(queryset, 25).get_page(request.GET.get('page')), 'query_string': 'unread=1' if request.GET.get('unread') == '1' else ''})


@login_required
@require_POST
def notification_read(request, pk):
    item = get_object_or_404(Notification, recipient=request.user, pk=pk)
    item.is_read = True
    item.save(update_fields=['is_read'])
    url = item.url
    return redirect(url if url.startswith('/') and url_has_allowed_host_and_scheme(url, allowed_hosts={request.get_host()}, require_https=request.is_secure()) else 'dashboard')


@login_required
@require_POST
def notifications_read_all(request):
    Notification.objects.filter(recipient=request.user, is_read=False).update(is_read=True)
    return redirect('notifications')


def conversation_scope(user):
    return Q(participant_a=user) | Q(participant_b=user)


@login_required
@require_POST
def conversation_start(request, kind, pk):
    if kind == 'interviews':
        from .interview_services import participants
        obj = get_object_or_404(Interview.objects.filter(participants(request.user)).select_related('company__owner', 'worker'), pk=pk)
        recipient = obj.company.owner if obj.worker_id == request.user.pk else obj.worker
        subject = obj.title
    elif kind == 'orders':
        obj = get_object_or_404(Order.objects.filter(Q(customer=request.user) | Q(service__owner=request.user)).select_related('service__owner', 'customer'), pk=pk)
        recipient = obj.service.owner if obj.customer_id == request.user.pk else obj.customer
        subject = obj.service.title
    elif kind == 'rentals':
        obj = get_object_or_404(Rental.objects.filter(Q(customer__owner=request.user) | Q(offer__company__owner=request.user)).select_related('customer__owner', 'offer__company__owner'), pk=pk)
        recipient = obj.offer.company.owner if obj.customer.owner_id == request.user.pk else obj.customer.owner
        subject = obj.offer.specialty
    elif kind == 'invitations':
        obj = get_object_or_404(Invitation.objects.filter(Q(worker=request.user) | Q(company__owner=request.user)).select_related('company__owner', 'worker'), pk=pk)
        recipient = obj.company.owner if obj.worker_id == request.user.pk else obj.worker
        subject = 'Собеседование · ' + obj.company.name
    else:
        obj = get_listing(request.user, kind, pk)
        if kind == 'vacancies':
            if request.user.role != 'worker':
                raise PermissionDenied
            recipient = obj.company.owner
        elif kind in ['services', 'resumes']:
            if request.user.role != 'employer':
                raise PermissionDenied
            recipient = obj.owner
        else:
            recipient = obj.company.owner
        subject = str(obj)
    if recipient.pk == request.user.pk:
        messages.info(request, 'Это ваша публикация.')
        return redirect('dashboard')
    a, b = sorted([request.user.pk, recipient.pk])
    conversation, _ = Conversation.objects.get_or_create(
        participant_a_id=a, participant_b_id=b, defaults={'subject': subject[:160]},
    )
    return redirect('conversation', pk=conversation.pk)


@login_required
def inbox(request):
    last = Message.objects.filter(conversation=OuterRef('pk')).order_by('-created_at', '-pk')
    queryset = Conversation.objects.filter(conversation_scope(request.user)).select_related('participant_a', 'participant_b').annotate(
        unread_count=Count('messages', filter=Q(messages__is_read=False) & ~Q(messages__sender=request.user)),
        last_text=Subquery(last.values('text')[:1]),
    ).order_by('-updated_at', '-pk')
    q = request.GET.get('q', '').strip()[:160]
    if q:
        queryset = queryset.filter(Q(subject__icontains=q) | Q(participant_a__first_name__icontains=q) | Q(participant_b__first_name__icontains=q))
    page = Paginator(queryset, 20).get_page(request.GET.get('page'))
    for conversation in page:
        conversation.partner = conversation.participant_b if conversation.participant_a_id == request.user.pk else conversation.participant_a
    params = request.GET.copy()
    params.pop('page', None)
    return render(request, 'marketplace/inbox.html', {'items': page, 'q': q, 'query_string': params.urlencode()})


@login_required
def conversation(request, pk):
    item = get_object_or_404(Conversation.objects.filter(conversation_scope(request.user)).select_related('participant_a', 'participant_b'), pk=pk)
    partner = item.participant_b if item.participant_a_id == request.user.pk else item.participant_a
    form = MessageForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            Message.objects.create(conversation=item, sender=request.user, text=form.cleaned_data['text'])
            Conversation.objects.filter(pk=pk).update(updated_at=timezone.now())
            notify(partner.pk, f'Сообщение от {request.user}', form.cleaned_data['text'][:180], reverse('conversation', args=[pk]))
        return redirect('conversation', pk=pk)
    page = Paginator(item.messages.select_related('sender').order_by('-created_at', '-pk'), 40).get_page(request.GET.get('page'))
    rendered_messages = list(reversed(list(page)))
    Message.objects.filter(pk__in=[m.pk for m in rendered_messages], is_read=False).exclude(sender=request.user).update(is_read=True)
    return render(request, 'marketplace/conversation.html', {
        'conversation': item, 'partner': partner, 'chat_messages': rendered_messages, 'page': page, 'form': form,
    })
