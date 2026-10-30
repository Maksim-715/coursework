from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q, Count
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.urls import reverse
from django.views.decorators.http import require_POST
from .models import Company, Interview, PracticeInterview, PracticeAnswer, Invitation
from .interview_forms import InterviewForm, PracticeForm, ResultForm
from .interview_services import participants, schedule, transition
from .selectors import get_listing
from .practice import QUESTIONS


@login_required
def interviews(request):
    items = Interview.objects.filter(participants(request.user)).select_related('company', 'worker', 'vacancy')
    status = request.GET.get('status', '')
    tab = request.GET.get('tab', 'upcoming')
    if tab not in ['upcoming', 'history', 'all']:
        tab = 'upcoming'
    now = timezone.now()
    if tab == 'upcoming':
        items = items.filter(status__in=['pending', 'confirmed'], starts_at__gte=now).order_by('starts_at')
    elif tab == 'history':
        items = items.filter(Q(starts_at__lt=now) | ~Q(status__in=['pending', 'confirmed'])).order_by('-starts_at')
    else:
        items = items.order_by('-starts_at')
    if status in Interview.Status.values:
        items = items.filter(status=status)
    query = request.GET.get('q', '').strip()[:160]
    if query:
        items = items.filter(Q(title__icontains=query) | Q(company__name__icontains=query) | Q(worker__first_name__icontains=query) | Q(worker__last_name__icontains=query))
    params = request.GET.copy()
    params.pop('page', None)
    base = Interview.objects.filter(participants(request.user))
    return render(request, 'marketplace/interviews.html', {
        'items': Paginator(items, 15).get_page(request.GET.get('page')),
        'statuses': Interview.Status.choices, 'selected_status': status,
        'tab': tab, 'q': query, 'query_string': params.urlencode(),
        'upcoming_count': base.filter(status__in=['pending', 'confirmed'], starts_at__gte=now).count(),
        'pending_count': base.filter(status='pending', starts_at__gte=now).count(),
        'practices': PracticeInterview.objects.filter(owner=request.user)[:5],
    })


@login_required
def interview_edit(request, resume_pk=None, pk=None, invitation_pk=None):
    if request.user.role != 'employer':
        raise PermissionDenied
    company = Company.objects.filter(owner=request.user).first()
    if not company:
        messages.info(request, 'Сначала заполните профиль компании, чтобы назначать собеседования.')
        return redirect('profile')
    if pk:
        item = get_object_or_404(Interview, pk=pk, company=company)
        if not item.is_active:
            messages.error(request, 'Это собеседование нельзя перенести.')
            return redirect('interview_detail', pk=pk)
    elif invitation_pk:
        invitation = get_object_or_404(Invitation, pk=invitation_pk, company=company)
        item = Interview(company=company, worker=invitation.worker, description=invitation.message)
    else:
        resume = get_listing(request.user, 'resumes', resume_pk)
        item = Interview(company=company, worker=resume.owner)
    form = InterviewForm(request.POST if request.method == 'POST' else None, instance=item, company=company)
    if request.method == 'POST' and form.is_valid():
        try:
            item = schedule(form.save(commit=False), request.user)
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(request, 'Условия встречи сохранены. Изменённые условия требуют подтверждения кандидата.')
            return redirect('interview_detail', pk=item.pk)
    return render(request, 'marketplace/interview_form.html', {'form': form, 'title': 'Изменить собеседование' if pk else 'Назначить собеседование', 'obj': item.worker})


@login_required
def interview_detail(request, pk):
    item = get_object_or_404(Interview.objects.filter(participants(request.user)).select_related('company', 'worker', 'vacancy'), pk=pk)
    return render(request, 'marketplace/interview_detail.html', {'item': item, 'result_form': ResultForm(), 'can_confirm': item.starts_at > timezone.now(), 'events': item.events.select_related('actor'), 'is_past': item.ends_at <= timezone.now(), 'can_complete': item.status == 'confirmed' and item.ends_at <= timezone.now()})


@login_required
@require_POST
def interview_status(request, pk):
    target = request.POST.get('status', '')
    result = ''
    if target == 'completed':
        form = ResultForm(request.POST)
        if not form.is_valid():
            messages.error(request, 'Укажите итоги собеседования (до 10000 символов).')
            return redirect('interview_detail', pk=pk)
        result = form.cleaned_data['result']
    try:
        transition(request.user, pk, target, result, request.POST.get('reason', ''))
    except ValidationError as error:
        messages.error(request, ' '.join(error.messages))
    return redirect('interview_detail', pk=pk)


@login_required
def practice_create(request):
    form = PracticeForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            item = form.save(commit=False)
            item.owner = request.user
            item.save()
            PracticeAnswer.objects.bulk_create([
                PracticeAnswer(session=item, number=i, question=q, hint=h)
                for i, (q, h) in enumerate(QUESTIONS[item.topic], 1)
            ])
        return redirect('practice_detail', pk=item.pk)
    return render(request, 'marketplace/form.html', {'form': form, 'title': 'Тренировочное интервью'})


@login_required
def practice_history(request):
    items = PracticeInterview.objects.filter(owner=request.user).annotate(answered_count=Count('answers', filter=~Q(answers__answer=''))).order_by('-created_at', '-pk')
    return render(request, 'marketplace/practice_history.html', {'items': Paginator(items, 15).get_page(request.GET.get('page'))})


@login_required
def practice_detail(request, pk):
    with transaction.atomic():
        item = get_object_or_404(PracticeInterview.objects.select_for_update(), pk=pk, owner=request.user)
        answers = list(item.answers.all())
        try:
            step = max(1, min(len(answers), int(request.GET.get('step', 1))))
        except (ValueError, TypeError):
            step = 1
        current = answers[step - 1] if answers else None
        if request.method == 'POST' and not item.completed_at:
            submitted = [(a, request.POST[f'answer_{a.pk}'].strip()) for a in answers if f'answer_{a.pk}' in request.POST]
            if any(len(value) > 10000 for a, value in submitted):
                for a, value in submitted:
                    a.answer = value
                messages.error(request, 'Ответ должен содержать не более 10000 символов.')
            else:
                for a, value in submitted:
                    a.answer = value
                PracticeAnswer.objects.bulk_update([a for a, value in submitted], ['answer'])
                if request.POST.get('finish') == '1':
                    if all(a.answer for a in answers):
                        item.completed_at = timezone.now()
                        item.save(update_fields=['completed_at'])
                    else:
                        messages.error(request, 'Для завершения ответьте на все вопросы. Черновик сохранён.')
                        step = next((a.number for a in answers if not a.answer), 1)
                elif request.POST.get('next') == '1':
                    if current and current.answer:
                        step = min(step + 1, len(answers))
                    else:
                        messages.error(request, 'Напишите ответ перед переходом к следующему вопросу.')
                else:
                    messages.success(request, 'Ответ сохранён. Можно вернуться позже из истории тренировок.')
                return redirect(f"{reverse('practice_detail', args=[pk])}?step={step}")
    answered = sum(bool(a.answer) for a in answers)
    return render(request, 'marketplace/practice_detail.html', {
        'item': item, 'answers': answers, 'current': current, 'step': step,
        'answered': answered, 'progress': round(100 * answered / len(answers)) if answers else 0,
        'word_count': sum(len(a.answer.split()) for a in answers),
    })
