from django.db import models
from django.contrib.auth.models import AbstractUser
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db.models import Avg
from django.utils import timezone
from uuid import uuid4
from pathlib import Path
from .validators import validate_portfolio_attachment


def portfolio_path(instance, filename):
    return f"portfolio/{instance.owner_id}/{uuid4().hex}{Path(filename).suffix.lower()}"

class Category(models.TextChoices):
    HOSPITALITY = 'hospitality', 'Рестораны и гостеприимство'
    RETAIL = 'retail', 'Продажи и обслуживание'
    LOGISTICS = 'logistics', 'Логистика и склад'
    EVENTS = 'events', 'Мероприятия'
    CREATIVE = 'creative', 'Дизайн и творчество'
    IT = 'it', 'IT и технологии'
    HOME = 'home', 'Бытовые услуги'
    OTHER = 'other', 'Другое'


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
    city = models.CharField('Город', max_length=120, blank=True, db_index=True)
    website = models.URLField('Сайт компании', blank=True)
    def __str__(self): return self.name

class Resume(models.Model):
    owner = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='resume')
    specialization = models.CharField('Специализация', max_length=160)
    skills = models.TextField('Навыки')
    experience = models.TextField('Опыт работы')
    contacts = models.TextField('Контакты')
    portfolio = models.TextField('Портфолио: ссылки и описание работ', blank=True)
    city = models.CharField('Город', max_length=120, blank=True, db_index=True)
    desired_salary = models.PositiveIntegerField('Желаемая зарплата, ₽', null=True, blank=True)
    is_visible = models.BooleanField('Показывать резюме в поиске', default=True)
    def __str__(self): return self.specialization

class Vacancy(models.Model):
    city = models.CharField('Город / локация', max_length=120, blank=True, db_index=True)
    category = models.CharField('Категория', max_length=20, choices=Category.choices, default=Category.OTHER, db_index=True)
    is_active = models.BooleanField('Опубликовано', default=True, db_index=True)
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
        WITHDRAWN = 'withdrawn', 'Отозван соискателем'
        HIRED = 'hired', 'Принят на работу'
    vacancy = models.ForeignKey(Vacancy, on_delete=models.CASCADE, related_name='applications')
    worker = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    message = models.TextField('Сопроводительное письмо', blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.REVIEW)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['vacancy', 'worker'], name='unique_application')]

class Invitation(models.Model):
    class Status(models.TextChoices):
        NEW = 'new', 'Ожидает ответа'
        ACCEPTED = 'accepted', 'Принято'
        DECLINED = 'declined', 'Отклонено'
    status = models.CharField('Ответ', max_length=12, choices=Status.choices, default=Status.NEW)
    company = models.ForeignKey(Company, on_delete=models.CASCADE)
    worker = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    message = models.TextField('Приглашение на собеседование')
    created_at = models.DateTimeField(auto_now_add=True)

class Service(models.Model):
    city = models.CharField('Город / локация', max_length=120, blank=True, db_index=True)
    category = models.CharField('Категория', max_length=20, choices=Category.choices, default=Category.OTHER, db_index=True)
    is_active = models.BooleanField('Опубликовано', default=True, db_index=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
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
        CANCELLED = 'cancelled', 'Отменён заказчиком'
        REJECTED = 'rejected', 'Отклонён исполнителем'
    agreed_price = models.DecimalField('Стоимость при заказе, ₽', max_digits=10, decimal_places=2, null=True, editable=False)
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
    city = models.CharField('Город / локация', max_length=120, blank=True, db_index=True)
    category = models.CharField('Категория', max_length=20, choices=Category.choices, default=Category.OTHER, db_index=True)
    is_active = models.BooleanField('Опубликовано', default=True, db_index=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    company = models.ForeignKey(Company, on_delete=models.CASCADE)
    specialty = models.CharField('Специальность', max_length=160)
    count = models.PositiveIntegerField('Количество человек', validators=[MinValueValidator(1)])
    start = models.DateField('Начало срока')
    end = models.DateField('Конец срока')
    rate = models.DecimalField('Ставка за человека в день, ₽', max_digits=10, decimal_places=2, validators=[MinValueValidator(1)])
    description = models.TextField('Описание', blank=True)
    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(end__gte=models.F('start')), name='valid_staff_period')]
    def __str__(self): return self.specialty

class Rental(models.Model):
    class Status(models.TextChoices):
        NEW = 'new', 'На рассмотрении'
        ACCEPTED = 'accepted', 'Подтверждена'
        REJECTED = 'rejected', 'Отклонена'
        CANCELLED = 'cancelled', 'Отменена заказчиком'
    agreed_rate = models.DecimalField('Ставка при заявке, ₽', max_digits=10, decimal_places=2, null=True, editable=False)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    offer = models.ForeignKey(StaffOffer, on_delete=models.CASCADE)
    customer = models.ForeignKey(Company, on_delete=models.CASCADE)
    count = models.PositiveIntegerField('Количество человек', validators=[MinValueValidator(1)])
    start = models.DateField('Начало аренды')
    end = models.DateField('Конец аренды')
    message = models.TextField('Комментарий', blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.NEW)

    @property
    def total_price(self):
        if self.agreed_rate is None: return None
        return self.agreed_rate * self.count * ((self.end - self.start).days + 1)


class PortfolioProject(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='portfolio_projects')
    title = models.CharField('Название проекта', max_length=160)
    description = models.TextField('О проекте')
    url = models.URLField('Ссылка на материалы', blank=True)
    attachment = models.FileField('Материал проекта', upload_to=portfolio_path, blank=True, validators=[validate_portfolio_attachment], help_text='PDF, PNG, JPEG или WebP до 10 МБ. Доступно вам и работодателям, которым виден ваш профиль или услуга.')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-pk']

    def __str__(self): return self.title


class Favorite(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='favorites')
    vacancy = models.ForeignKey(Vacancy, null=True, blank=True, on_delete=models.CASCADE)
    service = models.ForeignKey(Service, null=True, blank=True, on_delete=models.CASCADE)
    staff = models.ForeignKey(StaffOffer, null=True, blank=True, on_delete=models.CASCADE)
    resume = models.ForeignKey(Resume, null=True, blank=True, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-pk']
        constraints = [
            models.UniqueConstraint(fields=['user', field], name=f'unique_favorite_{field}')
            for field in ['vacancy', 'service', 'staff', 'resume']
        ] + [models.CheckConstraint(
            condition=(
                models.Q(vacancy__isnull=False, service__isnull=True, staff__isnull=True, resume__isnull=True) |
                models.Q(vacancy__isnull=True, service__isnull=False, staff__isnull=True, resume__isnull=True) |
                models.Q(vacancy__isnull=True, service__isnull=True, staff__isnull=False, resume__isnull=True) |
                models.Q(vacancy__isnull=True, service__isnull=True, staff__isnull=True, resume__isnull=False)
            ), name='favorite_exactly_one_target'
        )]

    @property
    def target(self):
        return self.vacancy or self.service or self.staff or self.resume

    @property
    def kind(self):
        if self.vacancy_id: return 'vacancies'
        if self.service_id: return 'services'
        if self.staff_id: return 'staff'
        return 'resumes'


class Notification(models.Model):
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notifications')
    title = models.CharField('Событие', max_length=200)
    text = models.TextField('Подробности', blank=True)
    url = models.CharField('Адрес страницы', max_length=250, default='/dashboard/')
    is_read = models.BooleanField('Прочитано', default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-pk']
        indexes = [models.Index(fields=['recipient', 'is_read'])]

    def __str__(self): return self.title


class Conversation(models.Model):
    participant_a = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='conversations_a')
    participant_b = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='conversations_b')
    subject = models.CharField('Тема', max_length=160)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-updated_at', '-pk']
        constraints = [
            models.UniqueConstraint(fields=['participant_a', 'participant_b'], name='unique_conversation_pair'),
            models.CheckConstraint(condition=models.Q(participant_a__lt=models.F('participant_b')), name='ordered_conversation_pair'),
        ]

    def __str__(self): return self.subject


class Message(models.Model):
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name='messages')
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    text = models.TextField('Сообщение', max_length=5000)
    is_read = models.BooleanField('Прочитано', default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at', 'pk']
        indexes = [models.Index(fields=['conversation', 'is_read'])]


class Interview(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Ожидает подтверждения'
        CONFIRMED = 'confirmed', 'Подтверждено'
        DECLINED = 'declined', 'Отклонено кандидатом'
        CANCELLED = 'cancelled', 'Отменено'
        COMPLETED = 'completed', 'Завершено'

    class Format(models.TextChoices):
        ONLINE = 'online', 'Онлайн'
        OFFICE = 'office', 'В офисе'
        PHONE = 'phone', 'По телефону'

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='interviews')
    worker = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='interviews')
    vacancy = models.ForeignKey(Vacancy, on_delete=models.SET_NULL, null=True, blank=True)
    title = models.CharField('Тема собеседования', max_length=160)
    starts_at = models.DateTimeField('Начало')
    duration = models.PositiveSmallIntegerField('Длительность, минут', default=60, validators=[MinValueValidator(15), MaxValueValidator(240)])
    format = models.CharField('Формат', max_length=10, choices=Format.choices, default=Format.ONLINE)
    location = models.CharField('Адрес или телефон', max_length=250, blank=True)
    meeting_url = models.URLField('Ссылка на встречу', blank=True)
    description = models.TextField('Что подготовить', blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    result = models.TextField('Итоги (видны обоим участникам)', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['starts_at', 'pk']

    @property
    def ends_at(self):
        from datetime import timedelta
        return self.starts_at + timedelta(minutes=self.duration)

    @property
    def is_active(self):
        return self.status in [self.Status.PENDING, self.Status.CONFIRMED]

    def __str__(self):
        return self.title


class PracticeInterview(models.Model):
    class Topic(models.TextChoices):
        GENERAL = 'general', 'Знакомство и мотивация'
        BEHAVIORAL = 'behavioral', 'Опыт и рабочие ситуации'
        IT = 'it', 'IT и технологии'

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='practice_interviews')
    topic = models.CharField('Тема тренировки', max_length=20, choices=Topic.choices)
    position = models.CharField('Желаемая должность', max_length=160)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-pk']


class PracticeAnswer(models.Model):
    session = models.ForeignKey(PracticeInterview, on_delete=models.CASCADE, related_name='answers')
    number = models.PositiveSmallIntegerField()
    question = models.TextField()
    hint = models.TextField()
    answer = models.TextField('Ваш ответ', blank=True)

    class Meta:
        ordering = ['number']
        constraints = [models.UniqueConstraint(fields=['session', 'number'], name='unique_practice_question')]


class InterviewEvent(models.Model):
    interview = models.ForeignKey(Interview, on_delete=models.CASCADE, related_name='events')
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    title = models.CharField(max_length=120)
    detail = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-pk']
