from django.db import models
from django.contrib.auth.models import AbstractUser
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db.models import Avg

class User(AbstractUser):
    class Role(models.TextChoices):
        EMPLOYER = 'employer', 'Работодатель'
        WORKER = 'worker', 'Соискатель'
    email = models.EmailField('Email', unique=True)
    role = models.CharField('Роль', max_length=10, choices=Role.choices)
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username', 'role']
    def __str__(self): return self.get_full_name() or self.email

class Company(models.Model):
    owner = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='company')
    name = models.CharField('Название компании', max_length=160)
    industry = models.CharField('Сфера деятельности', max_length=160)
    description = models.TextField('Описание')
    contacts = models.TextField('Контакты')
    def __str__(self): return self.name

class Resume(models.Model):
    owner = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='resume')
    specialization = models.CharField('Специализация', max_length=160)
    skills = models.TextField('Навыки')
    experience = models.TextField('Опыт работы')
    contacts = models.TextField('Контакты')
    portfolio = models.TextField('Портфолио: ссылки и описание работ', blank=True)
    def __str__(self): return self.specialization

class Vacancy(models.Model):
    class Kind(models.TextChoices):
        DAY = 'day', 'На один день'
        PERMANENT = 'permanent', 'Постоянная работа'
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='vacancies')
    title = models.CharField('Должность', max_length=160)
    requirements = models.TextField('Требования')
    salary = models.PositiveIntegerField('Зарплата, ₽', validators=[MinValueValidator(1)])
    format = models.CharField('Формат работы', max_length=120)
    kind = models.CharField('Тип', max_length=12, choices=Kind.choices)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta: ordering = ['-created_at']
    def __str__(self): return self.title

class Application(models.Model):
    class Status(models.TextChoices):
        REVIEW = 'review', 'На рассмотрении'
        INVITED = 'invited', 'Приглашение'
        REJECTED = 'rejected', 'Отказ'
    vacancy = models.ForeignKey(Vacancy, on_delete=models.CASCADE, related_name='applications')
    worker = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    message = models.TextField('Сопроводительное письмо', blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.REVIEW)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['vacancy', 'worker'], name='unique_application')]

class Invitation(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE)
    worker = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    message = models.TextField('Приглашение на собеседование')
    created_at = models.DateTimeField(auto_now_add=True)

class Service(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='services')
    title = models.CharField('Название', max_length=160)
    description = models.TextField('Описание')
    price = models.DecimalField('Стоимость, ₽', max_digits=10, decimal_places=2, validators=[MinValueValidator(1)])
    @property
    def rating(self): return self.orders.aggregate(value=Avg('review__rating'))['value']
    def __str__(self): return self.title

class Order(models.Model):
    class Status(models.TextChoices):
        NEW = 'new', 'Ожидает подтверждения'
        ACCEPTED = 'accepted', 'Подтверждён'
        WORKING = 'working', 'В работе'
        DONE = 'done', 'Выполнен'
    service = models.ForeignKey(Service, on_delete=models.PROTECT, related_name='orders')
    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    date = models.DateField('Дата выполнения')
    comment = models.TextField('Комментарий', blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.NEW)
    created_at = models.DateTimeField(auto_now_add=True)

class Review(models.Model):
    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name='review')
    rating = models.PositiveSmallIntegerField('Оценка', validators=[MinValueValidator(1), MaxValueValidator(5)])
    text = models.TextField('Отзыв')
    created_at = models.DateTimeField(auto_now_add=True)

class Availability(models.Model):
    worker = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    date = models.DateField('Дата')
    available = models.BooleanField('Готов к работе', default=True)
    note = models.CharField('Примечание', max_length=200, blank=True)
    class Meta:
        ordering = ['date']
        constraints = [models.UniqueConstraint(fields=['worker', 'date'], name='unique_availability')]

class StaffOffer(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE)
    specialty = models.CharField('Специальность', max_length=160)
    count = models.PositiveIntegerField('Количество человек', validators=[MinValueValidator(1)])
    start = models.DateField('Начало срока')
    end = models.DateField('Конец срока')
    rate = models.DecimalField('Ставка за человека в день, ₽', max_digits=10, decimal_places=2, validators=[MinValueValidator(1)])
    description = models.TextField('Описание', blank=True)
    class Meta:
        constraints = [models.CheckConstraint(check=models.Q(end__gte=models.F('start')), name='valid_staff_period')]
    def __str__(self): return self.specialty

class Rental(models.Model):
    class Status(models.TextChoices):
        NEW = 'new', 'На рассмотрении'
        ACCEPTED = 'accepted', 'Подтверждена'
        REJECTED = 'rejected', 'Отклонена'
    offer = models.ForeignKey(StaffOffer, on_delete=models.CASCADE)
    customer = models.ForeignKey(Company, on_delete=models.CASCADE)
    count = models.PositiveIntegerField('Количество человек', validators=[MinValueValidator(1)])
    start = models.DateField('Начало аренды')
    end = models.DateField('Конец аренды')
    message = models.TextField('Комментарий', blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.NEW)
