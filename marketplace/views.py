from functools import wraps
from datetime import timedelta
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q, Sum
from django.shortcuts import render, redirect, get_object_or_404
from django.http import Http404
from django.views.decorators.http import require_POST
from django.utils import timezone
from .forms import (RegisterForm, CompanyForm, ResumeForm, VacancyForm, ServiceForm,
                    InvitationForm, ApplicationForm, ReviewForm, AvailabilityForm,
                    OrderForm, StaffOfferForm, RentalForm)
from .models import (Company, Resume, Vacancy, Service, Invitation, Application,
                     Review, Availability, Order, StaffOffer, Rental)


def role_required(role):
    def decorate(view):
        @login_required
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if request.user.role != role: raise PermissionDenied
            return view(request, *args, **kwargs)
        return wrapped
    return decorate

def home(request):
    return render(request, 'marketplace/home.html', {'vacancies': Vacancy.objects.select_related('company')[:4], 'services': Service.objects.select_related('owner')[:3], 'vacancy_count': Vacancy.objects.count(), 'service_count': Service.objects.count(), 'company_count': Company.objects.count()})

def register(request):
    if request.user.is_authenticated: return redirect('dashboard')
    form = RegisterForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save(); login(request, user)
        return redirect('profile')
    return render(request, 'marketplace/form.html', {'form': form, 'title': 'Создать аккаунт'})

@login_required
def profile(request):
    model, form_class = (Company, CompanyForm) if request.user.role == 'employer' else (Resume, ResumeForm)
    instance = model.objects.filter(owner=request.user).first()
    form = form_class(request.POST or None, instance=instance)
    if request.method == 'POST' and form.is_valid():
        obj = form.save(commit=False); obj.owner = request.user; obj.save()
        messages.success(request, 'Профиль сохранён.'); return redirect('dashboard')
    return render(request, 'marketplace/form.html', {'form': form, 'title': 'Профиль компании' if model == Company else 'Моё резюме и портфолио'})

@login_required
def dashboard(request):
    u = request.user
    if u.role == 'employer':
        context = {'vacancies': Vacancy.objects.filter(company__owner=u), 'applications': Application.objects.filter(vacancy__company__owner=u).select_related('worker', 'vacancy'), 'orders': Order.objects.filter(customer=u).select_related('service', 'service__owner'), 'offers': StaffOffer.objects.filter(company__owner=u), 'rentals_in': Rental.objects.filter(offer__company__owner=u).select_related('customer', 'offer'), 'rentals_out': Rental.objects.filter(customer__owner=u).select_related('offer'), 'application_statuses': Application.Status.choices, 'rental_statuses': Rental.Status.choices}
    else:
        context = {'applications': Application.objects.filter(worker=u).select_related('vacancy', 'vacancy__company'), 'invitations': Invitation.objects.filter(worker=u).select_related('company'), 'services': Service.objects.filter(owner=u), 'orders': Order.objects.filter(service__owner=u).select_related('service', 'customer'), 'availability': Availability.objects.filter(worker=u), 'reviews': Review.objects.filter(order__service__owner=u).select_related('order__service'), 'availability_form': AvailabilityForm(), 'order_statuses': Order.Status.choices}
        import calendar
        from datetime import date
        today = timezone.localdate()
        try:
            year, month = int(request.GET.get('year', today.year)), int(request.GET.get('month', today.month))
            if not 1900 <= year <= 2100: raise ValueError
            first = date(year, month, 1)
        except (ValueError, OverflowError):
            first = today.replace(day=1)
        year, month = first.year, first.month
        days = {item.date: item for item in Availability.objects.filter(worker=u, date__year=year, date__month=month)}
        booked = set(Order.objects.filter(service__owner=u, date__year=year, date__month=month, status__in=['accepted', 'working']).values_list('date', flat=True))
        context['calendar_weeks'] = [[{'day': day.day, 'in_month': day.month == month, 'today': day == today, 'availability': days.get(day), 'booked': day in booked} for day in week] for week in calendar.Calendar().monthdatescalendar(year, month)]
        names = ['Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь', 'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь']
        context['weekdays'] = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']
        context['calendar_title'] = f'{names[month-1]} {year}'
        context['prev_month'] = (first-timedelta(days=1)).replace(day=1)
        context['next_month'] = (first+timedelta(days=32)).replace(day=1)
    return render(request, 'marketplace/dashboard.html', context)

def catalog(request, kind):
    if kind not in ['vacancies', 'services', 'staff', 'resumes']: raise Http404
    q = request.GET.get('q', '').strip()
    if kind == 'vacancies':
        items = Vacancy.objects.select_related('company')
        if q: items = items.filter(Q(title__icontains=q) | Q(requirements__icontains=q))
        if request.GET.get('kind') in Vacancy.Kind.values: items = items.filter(kind=request.GET['kind'])
        salary = request.GET.get('salary', '')
        if salary.isdecimal() and len(salary) <= 10: items = items.filter(salary__gte=min(int(salary), 2147483647))
        title, subtitle = 'Найдите свою работу', 'Один день или новый этап карьеры — решать вам.'
    elif kind == 'services':
        items = Service.objects.select_related('owner')
        if q: items = items.filter(Q(title__icontains=q) | Q(description__icontains=q))
        title, subtitle = 'Специалисты для ваших задач', 'Нужная помощь рядом. Выбирайте, заказывайте, оценивайте.'
    elif kind == 'staff':
        if not request.user.is_authenticated: return redirect('login')
        if request.user.role != 'employer': raise PermissionDenied
        items = StaffOffer.objects.select_related('company').exclude(company__owner=request.user)
        if q: items = items.filter(specialty__icontains=q)
        title, subtitle = 'Команда на нужный срок', 'Арендуйте сотрудников у проверенных компаний.'
    else:
        if not request.user.is_authenticated: return redirect('login')
        if request.user.role != 'employer': raise PermissionDenied
        items = Resume.objects.select_related('owner')
        if q: items = items.filter(Q(specialization__icontains=q) | Q(skills__icontains=q))
        title, subtitle = 'Найдите своего специалиста', 'Опыт, навыки и портфолио в одном месте.'
    from django.core.paginator import Paginator
    page = Paginator(items.order_by('-pk'), 12).get_page(request.GET.get('page'))
    return render(request, 'marketplace/catalog.html', {'items': page, 'kind': kind, 'title': title, 'subtitle': subtitle, 'q': q})

def detail(request, kind, pk):
    if kind not in ['vacancies', 'services', 'staff', 'resumes']: raise Http404
    model = {'vacancies': Vacancy, 'services': Service, 'staff': StaffOffer, 'resumes': Resume}[kind]
    if kind in ['staff', 'resumes'] and (not request.user.is_authenticated or request.user.role != 'employer'): raise PermissionDenied
    obj = get_object_or_404(model, pk=pk)
    reviews = Review.objects.filter(order__service=obj).select_related('order__customer') if kind == 'services' else []
    return render(request, 'marketplace/detail.html', {'obj': obj, 'kind': kind, 'reviews': reviews})

@login_required
def edit(request, kind, pk=None):
    if kind not in ['vacancy', 'service', 'staff']: raise Http404
    if kind == 'vacancy': model, form_class, role = Vacancy, VacancyForm, 'employer'
    elif kind == 'service': model, form_class, role = Service, ServiceForm, 'worker'
    else: model, form_class, role = StaffOffer, StaffOfferForm, 'employer'
    if request.user.role != role: raise PermissionDenied
    owner_filter = {'owner': request.user} if kind == 'service' else {'company__owner': request.user}
    obj = get_object_or_404(model, pk=pk, **owner_filter) if pk else None
    company = Company.objects.filter(owner=request.user).first() if role == 'employer' else None
    if role == 'employer' and not company:
        messages.info(request, 'Сначала заполните профиль компании.'); return redirect('profile')
    form = form_class(request.POST or None, instance=obj)
    if request.method == 'POST' and form.is_valid():
        obj = form.save(commit=False)
        if kind == 'service': obj.owner = request.user
        else: obj.company = company
        obj.save(); messages.success(request, 'Сохранено.'); return redirect('dashboard')
    return render(request, 'marketplace/form.html', {'form': form, 'title': 'Редактирование' if pk else 'Новая публикация'})

@login_required
def delete(request, kind, pk):
    if kind not in ['vacancy', 'service', 'staff']: raise Http404
    model = {'vacancy': Vacancy, 'service': Service, 'staff': StaffOffer}[kind]
    owner_filter = {'owner': request.user} if kind == 'service' else {'company__owner': request.user}
    obj = get_object_or_404(model, pk=pk, **owner_filter)
    if request.method == 'POST':
        from django.db.models.deletion import ProtectedError
        try: obj.delete(); messages.success(request, 'Публикация удалена.')
        except ProtectedError: messages.error(request, 'Услуга связана с заказами и не может быть удалена.')
        return redirect('dashboard')
    return render(request, 'marketplace/delete.html', {'obj': obj})

@login_required
def action(request, kind, pk):
    if kind not in ['apply', 'invite', 'order', 'rent', 'review']: raise Http404
    u = request.user
    if kind == 'apply':
        if u.role != 'worker': raise PermissionDenied
        obj = get_object_or_404(Vacancy, pk=pk); form = ApplicationForm(request.POST or None)
        if not Resume.objects.filter(owner=u).exists():
            messages.info(request, 'Заполните резюме перед откликом.'); return redirect('profile')
    elif kind == 'invite':
        if u.role != 'employer': raise PermissionDenied
        obj = get_object_or_404(Resume, pk=pk); form = InvitationForm(request.POST or None)
        if not Company.objects.filter(owner=u).exists(): return redirect('profile')
    elif kind == 'order':
        if u.role != 'employer': raise PermissionDenied
        obj = get_object_or_404(Service, pk=pk); form = OrderForm(request.POST or None)
    elif kind == 'rent':
        if u.role != 'employer': raise PermissionDenied
        obj = get_object_or_404(StaffOffer.objects.exclude(company__owner=u), pk=pk)
        if not Company.objects.filter(owner=u).exists(): return redirect('profile')
        form = RentalForm(request.POST or None, offer=obj)
    else:
        obj = get_object_or_404(Order, pk=pk, customer=u, status='done')
        if Review.objects.filter(order=obj).exists():
            messages.info(request, 'Вы уже оставили отзыв.'); return redirect('dashboard')
        form = ReviewForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        item = form.save(commit=False)
        if kind == 'apply':
            _, created = Application.objects.get_or_create(vacancy=obj, worker=u, defaults={'message': item.message})
            messages.success(request, 'Отклик отправлен.' if created else 'Вы уже откликнулись.'); return redirect('dashboard')
        if kind == 'invite': item.company = u.company; item.worker = obj.owner
        elif kind == 'order': item.customer = u; item.service = obj
        elif kind == 'rent': item.customer = u.company; item.offer = obj
        else: item.order = obj
        item.save(); messages.success(request, 'Готово!'); return redirect('dashboard')
    titles = {'apply': 'Отклик на вакансию', 'invite': 'Приглашение на собеседование', 'order': 'Заказать услугу', 'rent': 'Заявка на аренду', 'review': 'Оставить отзыв'}
    return render(request, 'marketplace/form.html', {'form': form, 'title': titles[kind], 'obj': obj})

@login_required
@require_POST
def status(request, kind, pk):
    if kind not in ['application', 'order', 'rental']: raise Http404
    value = request.POST.get('status')
    if kind == 'application':
        obj = get_object_or_404(Application, pk=pk, vacancy__company__owner=request.user)
        if value not in Application.Status.values: raise PermissionDenied
    elif kind == 'order':
        obj = get_object_or_404(Order, pk=pk, service__owner=request.user)
        transitions = {'new': 'accepted', 'accepted': 'working', 'working': 'done'}
        if transitions.get(obj.status) != value:
            messages.error(request, 'Статусы заказа меняются последовательно.'); return redirect('dashboard')
    else:
        with transaction.atomic():
            rental = get_object_or_404(Rental, pk=pk, offer__company__owner=request.user)
            offer = StaffOffer.objects.select_for_update().get(pk=rental.offer_id)
            obj = Rental.objects.select_for_update().get(pk=pk)
            if value not in Rental.Status.values: raise PermissionDenied
            if value == 'accepted' and not (offer.start <= obj.start <= obj.end <= offer.end and obj.count <= offer.count):
                messages.error(request, 'Условия предложения изменились. Попросите клиента отправить новую заявку.'); return redirect('dashboard')
            reserved = Rental.objects.filter(offer=offer, status='accepted', start__lte=obj.end, end__gte=obj.start).exclude(pk=obj.pk).aggregate(total=Sum('count'))['total'] or 0
            if value == 'accepted' and reserved + obj.count > offer.count:
                messages.error(request, 'На эти даты недостаточно свободных сотрудников.'); return redirect('dashboard')
            obj.status = value; obj.save(update_fields=['status'])
        messages.success(request, 'Статус обновлён.'); return redirect('dashboard')
    obj.status = value; obj.save(update_fields=['status'])
    messages.success(request, 'Статус обновлён.'); return redirect('dashboard')

@role_required('worker')
@require_POST
def availability(request):
    form = AvailabilityForm(request.POST)
    if form.is_valid():
        Availability.objects.update_or_create(worker=request.user, date=form.cleaned_data['date'], defaults={'available': form.cleaned_data['available'], 'note': form.cleaned_data['note']})
        messages.success(request, 'Календарь обновлён.')
    else: messages.error(request, form.errors.as_text())
    return redirect('dashboard')

@role_required('worker')
@require_POST
def availability_delete(request, pk):
    get_object_or_404(Availability, pk=pk, worker=request.user).delete()
    return redirect('dashboard')
