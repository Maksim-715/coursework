import calendar
from datetime import date, timedelta
from functools import wraps

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Avg, Count, F, Q, Sum
from django.db.models.deletion import ProtectedError
from django.http import Http404, FileResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django.utils import timezone

from .forms import (RegisterForm, CompanyForm, ResumeForm, VacancyForm, ServiceForm,
                    InvitationForm, ApplicationForm, ReviewForm, AvailabilityForm,
                    OrderForm, StaffOfferForm, RentalForm, PortfolioForm, SearchForm)
from .models import (Company, Resume, Vacancy, Service, Invitation, Application,
                     Review, Availability, Order, StaffOffer, Rental, PortfolioProject, Favorite, User, Category, Interview)
from .selectors import check_catalog_access, get_listing, FAVORITE_FIELDS
from .services import notify, move_order, move_rental, move_application, respond_invitation, peak_reserved


def role_required(role):
    def decorate(view):
        @login_required
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if request.user.role != role:
                raise PermissionDenied
            return view(request, *args, **kwargs)
        return wrapped
    return decorate


def home(request):
    return render(request, 'marketplace/home.html', {
        'vacancies': Vacancy.objects.filter(is_active=True).select_related('company')[:4],
        'vacancy_count': Vacancy.objects.filter(is_active=True).count(),
        'service_count': Service.objects.filter(is_active=True).count(),
        'company_count': Company.objects.count(),
        'featured_services': Service.objects.filter(is_active=True).select_related('owner').annotate(average_rating=Avg('orders__review__rating'), reviews_count=Count('orders__review')).order_by('-created_at', '-pk')[:3],
        'categories': Category.choices,
    })


def register(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    role = request.GET.get('role', 'worker')
    form = RegisterForm(request.POST or None, initial={'role': role if role in User.Role.values else 'worker'})
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            user = form.save()
            notify(user.pk, 'Добро пожаловать в Смену!', 'Заполните профиль — так другим участникам будет проще найти вас.', '/profile/')
        login(request, user)
        return redirect('profile')
    return render(request, 'marketplace/form.html', {'form': form, 'title': 'Создать аккаунт'})


@login_required
def profile(request):
    model, form_class = (Company, CompanyForm) if request.user.role == 'employer' else (Resume, ResumeForm)
    instance = model.objects.filter(owner=request.user).first()
    form = form_class(request.POST or None, instance=instance)
    if request.method == 'POST' and form.is_valid():
        obj = form.save(commit=False)
        obj.owner = request.user
        obj.save()
        messages.success(request, 'Профиль сохранён.')
        return redirect('dashboard')
    return render(request, 'marketplace/form.html', {
        'form': form, 'title': 'Профиль компании' if model == Company else 'Моё резюме и портфолио',
    })


def calendar_context(user, params):
    today = timezone.localdate()
    try:
        year, month = int(params.get('year', today.year)), int(params.get('month', today.month))
        if not 1900 <= year <= 2100:
            raise ValueError
        first = date(year, month, 1)
    except (ValueError, OverflowError):
        first = today.replace(day=1)
    year, month = first.year, first.month
    days = {item.date: item for item in Availability.objects.filter(worker=user, date__year=year, date__month=month)}
    booked = set(Order.objects.filter(service__owner=user, date__year=year, date__month=month,
                                     status__in=['accepted', 'working', 'done']).values_list('date', flat=True))
    interview_days = {}
    for item in Interview.objects.filter(worker=user, starts_at__date__year=year, starts_at__date__month=month,
                                         status__in=['pending', 'confirmed']).order_by('starts_at'):
        interview_days.setdefault(timezone.localtime(item.starts_at).date(), []).append(item)
    names = ['Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь', 'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь']
    return {
        'calendar_weeks': [[{'day': day.day, 'in_month': day.month == month, 'today': day == today,
                            'availability': days.get(day), 'booked': day in booked, 'interviews': interview_days.get(day, [])}
                           for day in week] for week in calendar.Calendar().monthdatescalendar(year, month)],
        'weekdays': ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'],
        'calendar_title': f'{names[month-1]} {year}',
        'prev_month': (first-timedelta(days=1)).replace(day=1),
        'next_month': (first+timedelta(days=32)).replace(day=1),
    }


@login_required
def dashboard(request):
    user = request.user
    is_employer = user.role == 'employer'
    orders = Order.objects.filter(customer=user) if is_employer else Order.objects.filter(service__owner=user)
    applications = Application.objects.filter(vacancy__company__owner=user) if is_employer else Application.objects.filter(worker=user)
    from .interview_services import participants
    context = {
        'upcoming_interviews': Interview.objects.filter(participants(user), status__in=['pending', 'confirmed'], starts_at__gte=timezone.now()).select_related('company', 'worker')[:3],
        'applications': applications.select_related('worker', 'worker__resume', 'vacancy__company').order_by('-created_at'),
        'orders': orders.select_related('service__owner', 'customer', 'review').order_by('-created_at'),
        'application_statuses': [(v, label) for v, label in Application.Status.choices if v != 'withdrawn'],
        'application_filters': Application.Status.choices,
        'stats': {
            'applications': applications.filter(status='review').count(),
            'orders': orders.filter(status__in=['new', 'accepted', 'working']).count(),
            'favorites': Favorite.objects.filter(user=user).count(),
            'completed': orders.filter(status='done').count(),
        },
        'recent_notifications': user.notifications.all()[:4],
        'today': timezone.localdate(),
    }
    application_status = request.GET.get('application_status', '')
    if application_status in Application.Status.values:
        context['applications'] = context['applications'].filter(status=application_status)
    if is_employer:
        context.update({
            'vacancies': Vacancy.objects.filter(company__owner=user).annotate(response_count=Count('applications')).order_by('-created_at', '-pk'),
            'offers': StaffOffer.objects.filter(company__owner=user).order_by('-created_at'),
            'rentals_in': Rental.objects.filter(offer__company__owner=user).select_related('customer', 'offer').order_by('-created_at'),
            'rentals_out': Rental.objects.filter(customer__owner=user).select_related('offer__company').order_by('-created_at'),
            'invitations': Invitation.objects.filter(company__owner=user).select_related('worker').order_by('-created_at'),
            'profile_ready': Company.objects.filter(owner=user).exists(),
        })
    else:
        context.update({
            'invitations': Invitation.objects.filter(worker=user).select_related('company').order_by('-created_at'),
            'services': Service.objects.filter(owner=user).annotate(review_count=Count('orders__review')).order_by('-created_at', '-pk'),
            'availability': Availability.objects.filter(worker=user, date__gte=timezone.localdate()),
            'reviews': Review.objects.filter(order__service__owner=user).select_related('order__service', 'order__customer').order_by('-created_at'),
            'availability_form': AvailabilityForm(),
            'portfolio_projects': PortfolioProject.objects.filter(owner=user),
            'profile_ready': Resume.objects.filter(owner=user).exists(),
            'earnings': orders.filter(status='done').aggregate(total=Sum('agreed_price'))['total'] or 0,
            'worker_rating': Review.objects.filter(order__service__owner=user).aggregate(value=Avg('rating'))['value'],
        })
        context.update(calendar_context(user, request.GET))
    sections = {
        'applications': 'applications', 'orders': 'orders', 'invitations': 'invitations',
        'vacancies': 'publications', 'services': 'publications', 'offers': 'rentals',
        'rentals_in': 'rentals-in', 'rentals_out': 'rentals-out', 'reviews': 'reviews',
        'portfolio_projects': 'portfolio', 'availability': 'calendar',
    }
    for key, anchor in sections.items():
        if key in context:
            per_page = 6 if key == 'portfolio_projects' else 10
            page = Paginator(context[key], per_page).get_page(request.GET.get(f'{key}_page'))
            params = request.GET.copy()
            params.pop(f'{key}_page', None)
            page.query_string = params.urlencode()
            page.page_key, page.anchor = f'{key}_page', anchor
            context[key] = page
    return render(request, 'marketplace/dashboard.html', context)


def catalog(request, kind):
    if kind in ['staff', 'resumes'] and not request.user.is_authenticated:
        return redirect('login')
    check_catalog_access(request.user, kind)
    if kind == 'vacancies':
        items = Vacancy.objects.filter(is_active=True).select_related('company')
        title, subtitle = 'Найдите свою работу', 'Один день или новый этап карьеры — решать вам.'
        text_fields, price_field = ['title', 'requirements', 'company__name'], 'salary'
    elif kind == 'services':
        items = Service.objects.filter(is_active=True).select_related('owner').annotate(
            average_rating=Avg('orders__review__rating'), reviews_count=Count('orders__review'))
        title, subtitle = 'Специалисты для ваших задач', 'Нужная помощь рядом. Выбирайте, заказывайте, оценивайте.'
        text_fields, price_field = ['title', 'description', 'owner__first_name', 'owner__last_name'], 'price'
    elif kind == 'staff':
        items = StaffOffer.objects.filter(is_active=True, end__gte=timezone.localdate()).exclude(company__owner=request.user).select_related('company')
        title, subtitle = 'Команда на нужный срок', 'Арендуйте сотрудников у компаний и закрывайте сезонные задачи.'
        text_fields, price_field = ['specialty', 'description', 'company__name'], 'rate'
    else:
        items = Resume.objects.filter(is_visible=True).select_related('owner')
        title, subtitle = 'Найдите своего специалиста', 'Опыт, навыки и портфолио в одном месте.'
        text_fields, price_field = ['specialization', 'skills', 'experience', 'owner__first_name', 'owner__last_name'], 'desired_salary'
    search_form = SearchForm(request.GET, kind=kind)
    if search_form.is_valid():
        data = search_form.cleaned_data
        if data.get('q'):
            query = Q()
            for field in text_fields:
                query |= Q(**{f'{field}__icontains': data['q']})
            items = items.filter(query)
        if data.get('city'):
            items = items.filter(city__icontains=data['city'])
        if data.get('category') and kind != 'resumes':
            items = items.filter(category=data['category'])
        if kind == 'vacancies':
            if data.get('kind'):
                items = items.filter(kind=data['kind'])
            if data.get('salary') is not None:
                items = items.filter(salary__gte=data['salary'])
        if kind in ['services', 'staff', 'resumes']:
            if data.get('min_price') is not None:
                items = items.filter(**{f'{price_field}__gte': data['min_price']})
            if data.get('max_price') is not None:
                items = items.filter(**{f'{price_field}__lte': data['max_price']})
        if kind == 'staff':
            if data.get('count'):
                items = items.filter(count__gte=data['count'])
            if data.get('start'):
                items = items.filter(start__lte=data['start'])
            if data.get('end'):
                items = items.filter(end__gte=data['end'])
        sort = data.get('sort')
        ordering = {'price_asc': F(price_field).asc(nulls_last=True), 'price_desc': F(price_field).desc(nulls_last=True)}
        if sort == 'rating' and kind == 'services':
            items = items.order_by(F('average_rating').desc(nulls_last=True), '-pk')
        else:
            items = items.order_by(ordering.get(sort, '-pk'), '-pk')
    else:
        items = items.none()
    page = Paginator(items, 12).get_page(request.GET.get('page'))
    if request.user.is_authenticated:
        field = FAVORITE_FIELDS[kind]
        ids = set(Favorite.objects.filter(user=request.user).values_list(f'{field}_id', flat=True))
        for item in page:
            item.is_favorite = item.pk in ids
    params = request.GET.copy()
    params.pop('page', None)
    return render(request, 'marketplace/catalog.html', {
        'items': page, 'kind': kind, 'title': title, 'subtitle': subtitle,
        'search_form': search_form, 'query_string': params.urlencode(),
    })


def detail(request, kind, pk):
    obj = get_listing(request.user, kind, pk)
    is_owner = request.user.is_authenticated and (obj.company.owner_id == request.user.pk if kind in ['vacancies', 'staff'] else obj.owner_id == request.user.pk)
    context = {'obj': obj, 'kind': kind, 'is_owner': is_owner}
    if kind == 'services':
        context['reviews'] = Review.objects.filter(order__service=obj).select_related('order__customer').order_by('-created_at')
        context['portfolio_projects'] = obj.owner.portfolio_projects.all()
    if kind == 'resumes':
        context['portfolio_projects'] = obj.owner.portfolio_projects.all()
    if request.user.is_authenticated:
        context['is_favorite'] = Favorite.objects.filter(user=request.user, **{FAVORITE_FIELDS[kind]: obj}).exists()
        if kind == 'vacancies':
            context['application'] = Application.objects.filter(vacancy=obj, worker=request.user).first()
    return render(request, 'marketplace/detail.html', context)


EDIT_TYPES = {
    'vacancy': (Vacancy, VacancyForm, 'employer'),
    'service': (Service, ServiceForm, 'worker'),
    'staff': (StaffOffer, StaffOfferForm, 'employer'),
    'portfolio': (PortfolioProject, PortfolioForm, 'worker'),
}


@login_required
def edit(request, kind, pk=None):
    if kind not in EDIT_TYPES:
        raise Http404
    model, form_class, role = EDIT_TYPES[kind]
    if request.user.role != role:
        raise PermissionDenied
    owner_filter = {'owner': request.user} if role == 'worker' else {'company__owner': request.user}
    obj = get_object_or_404(model, pk=pk, **owner_filter) if pk else None
    company = Company.objects.filter(owner=request.user).first() if role == 'employer' else None
    if role == 'employer' and not company:
        messages.info(request, 'Сначала заполните профиль компании.')
        return redirect('profile')
    form = form_class(request.POST or None, request.FILES or None, instance=obj)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            # The same offer lock is used by rental confirmation.
            if kind == 'staff' and obj:
                locked = StaffOffer.objects.select_for_update().get(pk=obj.pk)
                reserved = Rental.objects.filter(offer=locked, status='accepted').exists()
                if reserved and any(form.cleaned_data.get(f) != getattr(locked, f) for f in ['count', 'start', 'end']):
                    form.add_error(None, 'При подтверждённых заявках нельзя менять количество и период.')
                    return render(request, 'marketplace/form.html', {'form': form, 'title': 'Редактирование предложения'})
            item = form.save(commit=False)
            if role == 'worker':
                item.owner = request.user
            else:
                item.company = company
            item.save()
        messages.success(request, 'Сохранено.')
        return redirect('dashboard')
    return render(request, 'marketplace/form.html', {'form': form, 'title': ('Редактирование: ' if pk else '') + {'vacancy': 'Вакансия', 'service': 'Услуга', 'staff': 'Предложение персонала', 'portfolio': 'Проект портфолио'}[kind]})


@login_required
def delete(request, kind, pk):
    if kind not in EDIT_TYPES:
        raise Http404
    model, _, role = EDIT_TYPES[kind]
    if request.user.role != role:
        raise PermissionDenied
    owner_filter = {'owner': request.user} if role == 'worker' else {'company__owner': request.user}
    obj = get_object_or_404(model, pk=pk, **owner_filter)
    if request.method == 'POST':
        linked = (kind == 'vacancy' and obj.applications.exists()) or (kind == 'staff' and obj.rental_set.exists())
        if linked:
            messages.error(request, 'Есть связанные заявки. Отправьте публикацию в архив, чтобы сохранить историю.')
        else:
            try:
                obj.delete()
                messages.success(request, 'Публикация удалена.')
            except ProtectedError:
                messages.error(request, 'Услуга связана с заказами. Используйте архив.')
        return redirect('dashboard')
    return render(request, 'marketplace/delete.html', {'obj': obj})


@login_required
@require_POST
def archive(request, kind, pk):
    if kind not in EDIT_TYPES or kind == 'portfolio':
        raise Http404
    model, _, role = EDIT_TYPES[kind]
    if request.user.role != role:
        raise PermissionDenied
    filters = {'owner': request.user} if role == 'worker' else {'company__owner': request.user}
    with transaction.atomic():
        obj = get_object_or_404(model.objects.select_for_update(), pk=pk, **filters)
        obj.is_active = not obj.is_active
        obj.save(update_fields=['is_active'])
    messages.success(request, 'Публикация восстановлена.' if obj.is_active else 'Публикация в архиве. Текущие договорённости сохранены.')
    return redirect('dashboard')


@login_required
@transaction.atomic
def action(request, kind, pk):
    if kind not in ['apply', 'invite', 'order', 'rent', 'review']:
        raise Http404
    user = request.user
    if kind == 'apply':
        if user.role != 'worker':
            raise PermissionDenied
        obj = get_object_or_404(Vacancy.objects.select_for_update(), pk=pk, is_active=True)
        form = ApplicationForm(request.POST or None)
        if not Resume.objects.filter(owner=user).exists():
            messages.info(request, 'Заполните резюме перед откликом.')
            return redirect('profile')
    elif kind == 'invite':
        if user.role != 'employer':
            raise PermissionDenied
        obj = get_listing(user, 'resumes', pk)
        form = InvitationForm(request.POST or None)
        if not Company.objects.filter(owner=user).exists():
            return redirect('profile')
    elif kind == 'order':
        if user.role != 'employer':
            raise PermissionDenied
        obj = get_object_or_404(Service.objects.select_for_update(), pk=pk, is_active=True)
        form = OrderForm(request.POST or None, service=obj)
    elif kind == 'rent':
        if user.role != 'employer':
            raise PermissionDenied
        obj = get_object_or_404(StaffOffer.objects.select_for_update().exclude(company__owner=user), pk=pk, is_active=True)
        if not Company.objects.filter(owner=user).exists():
            return redirect('profile')
        form = RentalForm(request.POST or None, offer=obj)
    else:
        obj = get_object_or_404(Order.objects.select_for_update(), pk=pk, customer=user, status='done')
        if Review.objects.filter(order=obj).exists():
            messages.info(request, 'Вы уже оставили отзыв.')
            return redirect('dashboard')
        form = ReviewForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        item = form.save(commit=False)
        if kind == 'apply':
            application, created = Application.objects.get_or_create(vacancy=obj, worker=user, defaults={'message': item.message})
            if application.status == 'withdrawn':
                application.status, application.message = 'review', item.message
                application.save(update_fields=['status', 'message'])
                created = True
            if created:
                notify(obj.company.owner_id, 'Новый отклик', f'{user} · {obj.title}')
            messages.success(request, 'Отклик отправлен.' if created else 'Вы уже откликнулись.')
            return redirect('dashboard')
        if kind == 'invite':
            item.company, item.worker = user.company, obj.owner
            recipient, title, text = obj.owner_id, 'Приглашение на собеседование', user.company.name
        elif kind == 'order':
            item.customer, item.service, item.agreed_price = user, obj, obj.price
            recipient, title, text = obj.owner_id, 'Новый заказ услуги', obj.title
        elif kind == 'rent':
            item.customer, item.offer, item.agreed_rate = user.company, obj, obj.rate
            recipient, title, text = obj.company.owner_id, 'Новая заявка на аренду', obj.specialty
        else:
            item.order = obj
            recipient, title, text = obj.service.owner_id, 'Новый отзыв', f'{item.rating}/5 · {obj.service.title}'
        item.save()
        notify(recipient, title, text)
        messages.success(request, 'Готово!')
        return redirect('dashboard')
    titles = {'apply': 'Отклик на вакансию', 'invite': 'Приглашение на собеседование',
              'order': 'Заказать услугу', 'rent': 'Заявка на аренду', 'review': 'Оставить отзыв'}
    context = {'form': form, 'title': titles[kind], 'obj': obj,
               'submit_label': {'apply': 'Отправить отклик', 'invite': 'Отправить приглашение', 'order': 'Отправить заказ', 'rent': 'Отправить заявку', 'review': 'Опубликовать отзыв'}[kind]}
    if kind == 'order':
        context['quote_price'] = obj.price
        end = timezone.localdate() + timedelta(days=90)
        dates = set(Availability.objects.filter(worker=obj.owner, available=False, date__gte=timezone.localdate(), date__lte=end).values_list('date', flat=True))
        dates.update(Order.objects.filter(service__owner=obj.owner, status__in=['accepted', 'working'], date__gte=timezone.localdate(), date__lte=end).values_list('date', flat=True))
        context['busy_dates'] = [value.isoformat() for value in sorted(dates)]
    elif kind == 'rent':
        context['quote_rate'] = obj.rate
    return render(request, 'marketplace/form.html', context)


@login_required
@require_POST
def status(request, kind, pk):
    operations = {'application': move_application, 'order': move_order,
                  'rental': move_rental, 'invitation': respond_invitation}
    if kind not in operations:
        raise Http404
    try:
        operations[kind](request.user, pk, request.POST.get('status'))
    except ValidationError as error:
        messages.error(request, ' '.join(error.messages))
    else:
        messages.success(request, 'Статус обновлён.')
    return redirect('dashboard')


@role_required('worker')
@require_POST
@transaction.atomic
def availability(request):
    User.objects.select_for_update().get(pk=request.user.pk)
    form = AvailabilityForm(request.POST)
    if form.is_valid():
        data = form.cleaned_data
        if not data['available'] and Order.objects.filter(service__owner=request.user, date=data['date'], status__in=['accepted', 'working']).exists():
            messages.error(request, 'На эту дату уже есть подтверждённый заказ. Сначала обсудите изменение с заказчиком.')
        else:
            Availability.objects.update_or_create(worker=request.user, date=data['date'], defaults={'available': data['available'], 'note': data['note']})
            messages.success(request, 'Календарь обновлён.')
    else:
        messages.error(request, form.errors.as_text())
    return redirect('dashboard')


@role_required('worker')
@require_POST
def availability_delete(request, pk):
    get_object_or_404(Availability, pk=pk, worker=request.user).delete()
    return redirect('dashboard')


def company_detail(request, pk):
    company = get_object_or_404(Company, pk=pk)
    return render(request, 'marketplace/company.html', {
        'company': company, 'vacancies': company.vacancies.filter(is_active=True),
        'offers': StaffOffer.objects.filter(company=company, is_active=True, end__gte=timezone.localdate()) if request.user.is_authenticated and request.user.role == 'employer' else [],
    })


@login_required
def portfolio_download(request, pk):
    project = get_object_or_404(PortfolioProject.objects.select_related('owner'), pk=pk)
    if project.owner_id != request.user.pk and not request.user.has_perm('marketplace.view_portfolioproject'):
        if request.user.role != 'employer':
            raise PermissionDenied
        public_service = Service.objects.filter(owner=project.owner, is_active=True).exists()
        prior_order = Order.objects.filter(service__owner=project.owner, customer=request.user).exists()
        if not public_service and not prior_order:
            resume = get_object_or_404(Resume, owner=project.owner)
            get_listing(request.user, 'resumes', resume.pk)
    if not project.attachment:
        raise Http404
    try:
        attachment = project.attachment.open('rb')
    except (FileNotFoundError, OSError):
        raise Http404
    response = FileResponse(attachment, as_attachment=True, filename=project.attachment.name.rsplit('/', 1)[-1])
    response['X-Content-Type-Options'] = 'nosniff'
    response['Cache-Control'] = 'private, no-store'
    return response
