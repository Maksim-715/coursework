from datetime import timedelta
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from .models import *

class MarketplaceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.employer = User.objects.create_user(username='company', email='company@example.com', password='StrongPass123!', role='employer')
        cls.other = User.objects.create_user(username='other', email='other@example.com', password='StrongPass123!', role='employer')
        cls.worker = User.objects.create_user(username='worker', email='worker@example.com', password='StrongPass123!', role='worker')
        cls.company = Company.objects.create(owner=cls.employer, name='Компания', industry='IT', description='Описание', contacts='Email')
        cls.company2 = Company.objects.create(owner=cls.other, name='Клиент', industry='IT', description='Описание', contacts='Email')
        cls.resume = Resume.objects.create(owner=cls.worker, specialization='Дизайнер', skills='Figma', experience='3 года', contacts='Email')
        cls.vacancy = Vacancy.objects.create(company=cls.company, title='Дизайнер', requirements='Опыт', salary=80000, format='Удалённо', kind='permanent')
        cls.service = Service.objects.create(owner=cls.worker, title='Логотип', description='Дизайн', price=5000)
        cls.today = timezone.localdate()
        cls.offer = StaffOffer.objects.create(company=cls.company, specialty='Монтажник', count=3, start=cls.today, end=cls.today+timedelta(days=30), rate=2000)

    def test_email_login(self):
        self.assertTrue(self.client.login(username='worker@example.com', password='StrongPass123!'))

    def test_register_and_profile(self):
        response = self.client.post(reverse('register'), {'email': 'new@example.com', 'role': 'worker', 'first_name': 'Анна', 'password1': 'DifficultPassword734!', 'password2': 'DifficultPassword734!'})
        self.assertRedirects(response, reverse('profile'))
        self.assertEqual(User.objects.get(email='new@example.com').role, 'worker')
        self.assertRedirects(self.client.post(reverse('profile'), {'specialization': 'Повар', 'skills': 'Кухня', 'experience': '2 года', 'contacts': 'Телефон'}), reverse('dashboard'))

    def test_public_pages_and_templates(self):
        for path in ['/', '/accounts/login/', '/register/', '/catalog/vacancies/', '/catalog/services/', f'/catalog/vacancies/{self.vacancy.pk}/', f'/catalog/services/{self.service.pk}/']:
            self.assertEqual(self.client.get(path).status_code, 200, path)
        self.assertContains(self.client.get('/catalog/vacancies/?salary=90000'), 'Ничего не найдено')
        self.assertContains(self.client.get('/catalog/vacancies/?kind=day'), 'Ничего не найдено')

    def test_role_restrictions_and_ownership(self):
        self.client.force_login(self.worker)
        for path in ['/create/vacancy/', '/create/staff/', '/catalog/staff/', '/catalog/resumes/']:
            self.assertEqual(self.client.get(path).status_code, 403)
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(reverse('edit', args=['vacancy', self.vacancy.pk]), {}).status_code, 404)
        self.assertEqual(self.client.post(reverse('delete', args=['vacancy', self.vacancy.pk])).status_code, 404)
        self.assertTrue(Vacancy.objects.filter(pk=self.vacancy.pk).exists())
        self.assertEqual(self.client.get('/create/service/').status_code, 403)

    def test_application_unique_and_status_owner(self):
        self.client.force_login(self.worker)
        for _ in range(2): self.client.post(reverse('action', args=['apply', self.vacancy.pk]), {'message': 'Готов работать'})
        self.assertEqual(Application.objects.count(), 1)
        application = Application.objects.get()
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(reverse('status', args=['application', application.pk]), {'status': 'invited'}).status_code, 404)
        self.client.force_login(self.employer)
        self.client.post(reverse('status', args=['application', application.pk]), {'status': 'invited'})
        application.refresh_from_db(); self.assertEqual(application.status, 'invited')
        self.assertContains(self.client.get('/dashboard/'), 'Резюме')

    def test_invitation(self):
        self.client.force_login(self.employer)
        self.client.post(reverse('action', args=['invite', self.resume.pk]), {'message': 'Ждём на собеседовании'})
        self.client.force_login(self.worker)
        self.assertContains(self.client.get('/dashboard/'), 'Ждём на собеседовании')

    def test_order_lifecycle_and_review(self):
        self.client.force_login(self.employer)
        self.client.post(reverse('action', args=['order', self.service.pk]), {'date': self.today.isoformat(), 'comment': 'Новый бренд'})
        order = Order.objects.get()
        self.assertEqual(self.client.get(reverse('action', args=['review', order.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse('status', args=['order', order.pk]), {'status': 'done'}).status_code, 404)
        self.client.force_login(self.worker)
        self.client.post(reverse('status', args=['order', order.pk]), {'status': 'done'})
        order.refresh_from_db(); self.assertEqual(order.status, 'new')
        for value in ['accepted', 'working', 'done']:
            self.client.post(reverse('status', args=['order', order.pk]), {'status': value})
            order.refresh_from_db(); self.assertEqual(order.status, value)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse('action', args=['review', order.pk])).status_code, 404)
        self.client.force_login(self.employer)
        for _ in range(2): self.client.post(reverse('action', args=['review', order.pk]), {'rating': 5, 'text': 'Отличная работа'})
        self.assertEqual(Review.objects.count(), 1)
        self.assertEqual(self.service.rating, 5)
        self.assertContains(self.client.get(reverse('detail', args=['services', self.service.pk])), 'Отличная работа')

    def test_past_order_rejected(self):
        self.client.force_login(self.employer)
        response = self.client.post(reverse('action', args=['order', self.service.pk]), {'date': (self.today-timedelta(days=1)).isoformat()})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Order.objects.count(), 0)

    def test_rental_validation_and_capacity(self):
        self.client.force_login(self.other)
        url = reverse('action', args=['rent', self.offer.pk])
        self.client.post(url, {'count': 4, 'start': self.today, 'end': self.today})
        self.assertEqual(Rental.objects.count(), 0)
        self.client.post(url, {'count': 1, 'start': self.today, 'end': self.today+timedelta(days=31)})
        self.assertEqual(Rental.objects.count(), 0)
        for _ in range(2): self.client.post(url, {'count': 2, 'start': self.today, 'end': self.today})
        self.assertEqual(Rental.objects.count(), 2)
        self.client.force_login(self.employer)
        for rental in Rental.objects.all(): self.client.post(reverse('status', args=['rental', rental.pk]), {'status': 'accepted'})
        self.assertEqual(Rental.objects.filter(status='accepted').count(), 1)
        self.assertEqual(self.client.get(reverse('action', args=['rent', self.offer.pk])).status_code, 404)

    def test_availability_upsert(self):
        self.client.force_login(self.worker)
        self.client.post('/availability/', {'date': self.today, 'available': 'on', 'note': 'Готов'})
        self.client.post('/availability/', {'date': self.today, 'note': 'Занят'})
        self.assertEqual(Availability.objects.count(), 1)
        self.assertFalse(Availability.objects.get().available)
        self.assertEqual(self.client.get('/availability/').status_code, 405)

    def test_dashboards_and_forms(self):
        for user, paths in [(self.employer, ['/dashboard/', '/profile/', '/create/vacancy/', '/create/staff/', '/catalog/staff/', '/catalog/resumes/', f'/catalog/resumes/{self.resume.pk}/', f'/catalog/staff/{self.offer.pk}/']), (self.worker, ['/dashboard/', '/profile/', '/create/service/'])]:
            self.client.force_login(user)
            for path in paths: self.assertEqual(self.client.get(path).status_code, 200, path)

    def test_csrf_required(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.worker)
        self.assertEqual(client.post('/availability/', {'date': self.today}).status_code, 403)

    def test_unknown_routes_and_calendar_input(self):
        self.assertEqual(self.client.get('/catalog/unknown/').status_code, 404)
        self.assertEqual(self.client.get('/catalog/unknown/1/').status_code, 404)
        self.client.force_login(self.worker)
        self.assertEqual(self.client.get('/dashboard/?year=9999&month=12').status_code, 200)
        self.assertEqual(self.client.get('/dashboard/?year=abc&month=0').status_code, 200)

    def test_reserved_offer_cannot_change_period_or_quantity(self):
        Rental.objects.create(offer=self.offer, customer=self.company2, count=2, start=self.today, end=self.today, status='accepted')
        self.client.force_login(self.employer)
        response = self.client.post(reverse('edit', args=['staff', self.offer.pk]), {'specialty': self.offer.specialty, 'count': 1, 'start': self.today, 'end': self.offer.end, 'rate': 2000})
        self.assertContains(response, 'При подтверждённых заявках')
        self.offer.refresh_from_db()
        self.assertEqual(self.offer.count, 3)
