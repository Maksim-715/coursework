from uuid import uuid4
from django import forms
from django.db import models
from django.contrib.auth.forms import UserCreationForm
from django.utils import timezone
from .models import (User, Company, Resume, Vacancy, Service, Invitation,
                     Application, Review, Availability, Order, StaffOffer, Rental)

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

def model_form(model, fields):
    return forms.modelform_factory(model, fields=fields, widgets={f.name: forms.DateInput(attrs={'type': 'date'}) for f in model._meta.fields if isinstance(f, models.DateField) and not isinstance(f, models.DateTimeField)})
CompanyForm = model_form(Company, ['name', 'industry', 'description', 'contacts'])
ResumeForm = model_form(Resume, ['specialization', 'skills', 'experience', 'contacts', 'portfolio'])
VacancyForm = model_form(Vacancy, ['title', 'requirements', 'salary', 'format', 'kind'])
ServiceForm = model_form(Service, ['title', 'description', 'price'])
InvitationForm = model_form(Invitation, ['message'])
ApplicationForm = model_form(Application, ['message'])
ReviewForm = model_form(Review, ['rating', 'text'])
AvailabilityForm = model_form(Availability, ['date', 'available', 'note'])
class OrderForm(model_form(Order, ['date', 'comment'])):
    def clean_date(self):
        value = self.cleaned_data['date']
        if value < timezone.localdate(): raise forms.ValidationError('Выберите сегодняшнюю или будущую дату.')
        return value
class StaffOfferForm(model_form(StaffOffer, ['specialty', 'count', 'start', 'end', 'rate', 'description'])):
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
