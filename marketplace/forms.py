from uuid import uuid4
from django import forms
from django.db import models
from django.contrib.auth.forms import UserCreationForm
from django.utils import timezone
from .models import (User, Company, Resume, Vacancy, Service, Invitation,
                     Application, Review, Availability, Order, StaffOffer, Rental, PortfolioProject, Category)

class RegisterForm(UserCreationForm):
    class Meta:
        model = User
        fields = ['email', 'first_name', 'last_name', 'role']
    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if User.objects.filter(email__iexact=email).exists(): raise forms.ValidationError('Этот email уже зарегистрирован.')
        return email
    def save(self, commit=True):
        user = super().save(commit=False)
        user.username = uuid4().hex
        if commit: user.save()
        return user

class PrivateFileInput(forms.ClearableFileInput):
    template_name = "marketplace/widgets/private_file.html"


class ListingForm(forms.ModelForm):
    def clean_category(self):
        return self.cleaned_data.get("category") or Category.OTHER

def model_form(model, fields):
    form_class = forms.modelform_factory(model, form=ListingForm, fields=fields, widgets={f.name: forms.DateInput(attrs={'type': 'date'}) for f in model._meta.fields if isinstance(f, models.DateField) and not isinstance(f, models.DateTimeField)})
    if 'attachment' in form_class.base_fields:
        form_class.base_fields['attachment'].widget = PrivateFileInput(attrs={'accept': '.pdf,.png,.jpg,.jpeg,.webp'})
    if 'category' in form_class.base_fields:
        form_class.base_fields['category'].required = False
    return form_class
CompanyForm = model_form(Company, ['name', 'industry', 'city', 'description', 'contacts', 'website'])
ResumeForm = model_form(Resume, ['specialization', 'city', 'desired_salary', 'skills', 'experience', 'contacts', 'portfolio', 'is_visible'])
VacancyForm = model_form(Vacancy, ['title', 'category', 'city', 'requirements', 'salary', 'format', 'kind'])
ServiceForm = model_form(Service, ['title', 'category', 'city', 'description', 'price'])
InvitationForm = model_form(Invitation, ['message'])
ApplicationForm = model_form(Application, ['message'])
PortfolioForm = model_form(PortfolioProject, ['title', 'description', 'url', 'attachment'])
AccountForm = model_form(User, ['first_name', 'last_name'])
ReviewForm = model_form(Review, ['rating', 'text'])
AvailabilityForm = model_form(Availability, ['date', 'available', 'note'])
class OrderForm(model_form(Order, ['date', 'comment'])):
    def __init__(self, *args, service=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.service = service
        self.fields['date'].widget.attrs['min'] = timezone.localdate().isoformat()
    def clean_date(self):
        value = self.cleaned_data['date']
        if value < timezone.localdate(): raise forms.ValidationError('Выберите сегодняшнюю или будущую дату.')
        if self.service:
            busy = Availability.objects.filter(worker=self.service.owner, date=value, available=False).exists()
            booked = Order.objects.filter(service__owner=self.service.owner, date=value, status__in=['accepted', 'working']).exists()
            if busy or booked: raise forms.ValidationError('Исполнитель занят на эту дату. Выберите другую или обсудите время в переписке.')
        return value
class StaffOfferForm(model_form(StaffOffer, ['specialty', 'category', 'city', 'count', 'start', 'end', 'rate', 'description'])):
    def clean(self):
        data = super().clean()
        if data.get('start') and data.get('end') and data['end'] < data['start']: self.add_error('end', 'Конец срока должен быть не раньше начала.')
        if self.instance.pk and self.instance.rental_set.filter(status='accepted').exists():
            original = StaffOffer.objects.get(pk=self.instance.pk)
            if any(data.get(field) != getattr(original, field) for field in ['count', 'start', 'end']):
                raise forms.ValidationError('При подтверждённых заявках нельзя менять количество и период. Создайте отдельное предложение.')
        return data
class RentalForm(model_form(Rental, ['count', 'start', 'end', 'message'])):
    def __init__(self, *args, offer, **kwargs):
        super().__init__(*args, **kwargs)
        self.offer = offer
    def clean(self):
        data = super().clean()
        if data.get('count', 0) > self.offer.count: self.add_error('count', 'Превышено количество в предложении.')
        start, end = data.get('start'), data.get('end')
        if start and end and not (self.offer.start <= start <= end <= self.offer.end): self.add_error('end', 'Срок должен находиться внутри периода предложения.')
        if start and start < timezone.localdate(): self.add_error('start', 'Дата уже прошла.')
        return data


class MessageForm(forms.Form):
    text = forms.CharField(label='Сообщение', max_length=5000, strip=True,
                          widget=forms.Textarea(attrs={'rows': 3, 'placeholder': 'Напишите сообщение…'}))


class SearchForm(forms.Form):
    q = forms.CharField(label='Поиск', required=False, max_length=160)
    city = forms.CharField(label='Город', required=False, max_length=120)
    category = forms.ChoiceField(label='Категория', required=False, choices=[('', 'Все категории')] + list(Category.choices))
    kind = forms.ChoiceField(label='Тип занятости', required=False, choices=[('', 'Любой тип')] + list(Vacancy.Kind.choices))
    salary = forms.IntegerField(label='Зарплата от, ₽', required=False, min_value=0, max_value=2147483647)
    min_price = forms.DecimalField(label='Цена от, ₽', required=False, min_value=0, max_value=99999999, decimal_places=2)
    max_price = forms.DecimalField(label='Цена до, ₽', required=False, min_value=0, max_value=99999999, decimal_places=2)
    count = forms.IntegerField(label='Сотрудников от', required=False, min_value=1, max_value=100000)
    start = forms.DateField(label='Начало', required=False, widget=forms.DateInput(attrs={'type': 'date'}))
    end = forms.DateField(label='Конец', required=False, widget=forms.DateInput(attrs={'type': 'date'}))
    sort = forms.ChoiceField(label='Сортировка', required=False, choices=[('', 'Сначала новые'), ('price_asc', 'Сначала дешевле'), ('price_desc', 'Сначала дороже'), ('rating', 'По рейтингу')])

    def __init__(self, *args, kind='services', **kwargs):
        super().__init__(*args, **kwargs)
        allowed = {'q', 'city', 'sort'}
        allowed.update({
            'vacancies': {'category', 'kind', 'salary'},
            'services': {'category', 'min_price', 'max_price'},
            'staff': {'category', 'min_price', 'max_price', 'count', 'start', 'end'},
            'resumes': {'min_price', 'max_price'},
        }.get(kind, set()))
        for name in list(self.fields):
            if name not in allowed:
                self.fields.pop(name)
        self.fields['q'].widget.attrs['placeholder'] = 'Специальность, навык или название'
        self.fields['city'].widget.attrs['placeholder'] = 'Например, Казань'
        self.fields['sort'].choices = [('', 'Сначала новые'), ('price_asc', 'По оплате: сначала ниже'), ('price_desc', 'По оплате: сначала выше')]
        if kind == 'services':
            self.fields['sort'].choices += [('rating', 'По рейтингу')]
        if kind == 'resumes':
            self.fields['min_price'].label = 'Желаемая зарплата от, ₽'
            self.fields['max_price'].label = 'Желаемая зарплата до, ₽'

    def clean(self):
        data = super().clean()
        if data.get('min_price') is not None and data.get('max_price') is not None and data['min_price'] > data['max_price']:
            self.add_error('max_price', 'Верхняя граница должна быть не меньше нижней.')
        if data.get('start') and data.get('end') and data['start'] > data['end']:
            self.add_error('end', 'Конец периода должен быть не раньше начала.')
        return data
