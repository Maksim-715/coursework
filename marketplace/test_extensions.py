from datetime import timedelta
from decimal import Decimal
from tempfile import TemporaryDirectory
from io import StringIO
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import override_settings

from django.db import IntegrityError, transaction
from django.test import TestCase, Client
from django.urls import reverse

from .tests import MarketplaceTests
from .models import (User, Vacancy, Service, StaffOffer, Order, Rental, Application,
                     Invitation, Review, Availability, Favorite, Notification,
                     Conversation, Message, PortfolioProject)
from .services import peak_reserved


class ExtensionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        MarketplaceTests.setUpTestData.__func__(cls)

    def enter(self, user):
        self.client.force_login(user)

    def transition(self, kind, obj, value):
        return self.client.post(reverse('status', args=[kind, obj.pk]), {'status': value})

    def make_order(self, **kwargs):
        data = {'service': self.service, 'customer': self.employer, 'date': self.today, 'agreed_price': 5000}
        data.update(kwargs)
        return Order.objects.create(**data)

    def test_case_insensitive_email_login_and_inactive_account(self):
        self.assertTrue(self.client.login(username='  WORKER@EXAMPLE.COM ', password='StrongPass123!'))
        self.worker.is_active = False
        self.worker.save()
        self.assertFalse(self.client.login(username='worker@example.com', password='StrongPass123!'))

    def test_archive_hides_publication_and_blocks_new_application(self):
        self.enter(self.employer)
        self.client.post(reverse('archive', args=['vacancy', self.vacancy.pk]))
        self.vacancy.refresh_from_db()
        self.assertFalse(self.vacancy.is_active)
        self.assertContains(self.client.get('/catalog/vacancies/'), 'Ничего не найдено')
        self.enter(self.worker)
        self.assertEqual(self.client.get(reverse('action', args=['apply', self.vacancy.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('detail', args=['vacancies', self.vacancy.pk])).status_code, 404)
        self.enter(self.employer)
        self.assertEqual(self.client.get(reverse('detail', args=['vacancies', self.vacancy.pk])).status_code, 200)
        self.client.post(reverse('archive', args=['vacancy', self.vacancy.pk]))
        self.vacancy.refresh_from_db()
        self.assertTrue(self.vacancy.is_active)

    def test_archive_permissions_and_history_preservation(self):
        application = Application.objects.create(vacancy=self.vacancy, worker=self.worker)
        self.enter(self.other)
        self.assertEqual(self.client.post(reverse('archive', args=['vacancy', self.vacancy.pk])).status_code, 404)
        self.enter(self.employer)
        self.assertEqual(self.client.get(reverse('archive', args=['vacancy', self.vacancy.pk])).status_code, 405)
        self.client.post(reverse('delete', args=['vacancy', self.vacancy.pk]))
        self.assertTrue(Application.objects.filter(pk=application.pk).exists())
        self.client.post(reverse('archive', args=['vacancy', self.vacancy.pk]))
        self.enter(self.worker)
        self.assertEqual(self.client.get(reverse('detail', args=['vacancies', self.vacancy.pk])).status_code, 200)

    def test_city_category_price_and_sort_filters(self):
        Service.objects.filter(pk=self.service.pk).update(city='Казань', category='creative')
        expensive = Service.objects.create(owner=self.worker, title='Брендбук', description='Дизайн', price=20000, city='Казань', category='creative')
        response = self.client.get('/catalog/services/?city=Казань&category=creative&min_price=6000&max_price=25000')
        self.assertContains(response, 'Брендбук')
        self.assertNotContains(response, '>Логотип<')
        response = self.client.get('/catalog/services/?sort=price_desc')
        self.assertEqual([item.pk for item in response.context['items']], [expensive.pk, self.service.pk])
        response = self.client.get('/catalog/services/?min_price=9000&max_price=1000')
        self.assertContains(response, 'Верхняя граница')
        self.assertEqual(response.context['items'].paginator.count, 0)
        self.assertEqual(self.client.get('/catalog/vacancies/?salary=²').status_code, 200)

    def test_staff_period_count_filters(self):
        self.enter(self.other)
        response = self.client.get('/catalog/staff/', {'count': 4})
        self.assertEqual(response.context['items'].paginator.count, 0)
        response = self.client.get('/catalog/staff/', {'count': 3, 'start': self.today, 'end': self.offer.end})
        self.assertEqual(response.context['items'].paginator.count, 1)
        response = self.client.get('/catalog/staff/', {'start': self.offer.end, 'end': self.today})
        self.assertContains(response, 'Конец периода')

    def test_publication_create_defaults_and_profile_fields(self):
        self.enter(self.worker)
        self.client.post(reverse('create', args=['service']), {'title': 'Монтаж видео', 'description': 'Помогу', 'price': 2000})
        self.assertEqual(Service.objects.get(title='Монтаж видео').category, 'other')
        self.enter(self.employer)
        self.assertContains(self.client.get('/profile/'), 'Сайт компании')
        self.assertEqual(self.client.get(reverse('company_detail', args=[self.company.pk])).status_code, 200)

    def test_favorite_toggle_remove_and_constraints(self):
        self.enter(self.worker)
        url = reverse('favorite_toggle', args=['vacancies', self.vacancy.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.client.post(url)
        self.assertContains(self.client.get('/favorites/'), 'Дизайнер')
        favorite = Favorite.objects.get()
        self.enter(self.other)
        self.assertEqual(self.client.post(reverse('favorite_remove', args=[favorite.pk])).status_code, 404)
        self.enter(self.worker)
        self.client.post(url)
        self.assertFalse(Favorite.objects.exists())
        with self.assertRaises(IntegrityError), transaction.atomic():
            Favorite.objects.create(user=self.worker)

    def test_hidden_resume_privacy_in_search_detail_and_favorites(self):
        self.enter(self.employer)
        self.client.post(reverse('favorite_toggle', args=['resumes', self.resume.pk]))
        self.resume.is_visible = False
        self.resume.save()
        self.assertEqual(self.client.get(reverse('detail', args=['resumes', self.resume.pk])).status_code, 404)
        self.assertContains(self.client.get('/favorites/'), 'Публикация недоступна')
        response = self.client.get('/catalog/resumes/')
        self.assertEqual(response.context['items'].paginator.count, 0)
        Application.objects.create(vacancy=self.vacancy, worker=self.worker)
        self.assertEqual(self.client.get(reverse('detail', args=['resumes', self.resume.pk])).status_code, 200)

    def test_notifications_for_application_and_status(self):
        self.enter(self.worker)
        for _ in range(2): self.client.post(reverse('action', args=['apply', self.vacancy.pk]), {'message': 'Здравствуйте'})
        self.assertEqual(Notification.objects.filter(recipient=self.employer).count(), 1)
        application = Application.objects.get()
        self.enter(self.employer)
        for _ in range(2): self.transition('application', application, 'invited')
        self.assertEqual(Notification.objects.filter(recipient=self.worker).count(), 1)
        self.assertContains(self.client.get('/notifications/'), 'Новый отклик')

    def test_notification_read_is_scoped_and_post_only(self):
        own = Notification.objects.create(recipient=self.worker, title='Личное')
        alien = Notification.objects.create(recipient=self.other, title='Чужое')
        self.enter(self.worker)
        self.assertEqual(self.client.post(reverse('notification_read', args=[alien.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('notification_read', args=[own.pk])).status_code, 405)
        self.client.post('/notifications/read-all/')
        own.refresh_from_db(); alien.refresh_from_db()
        self.assertTrue(own.is_read)
        self.assertFalse(alien.is_read)
        self.assertEqual(self.client.get('/notifications/?unread=1').context['items'].paginator.count, 0)

    def test_notification_cannot_redirect_to_external_site(self):
        item = Notification.objects.create(recipient=self.worker, title='Событие', url='//example.com')
        self.enter(self.worker)
        self.assertRedirects(self.client.post(reverse('notification_read', args=[item.pk])), '/dashboard/')

    def start_chat(self):
        self.enter(self.worker)
        self.client.post(reverse('conversation_start', args=['vacancies', self.vacancy.pk]))
        return Conversation.objects.get()

    def test_conversation_pair_reused_from_different_contexts(self):
        chat = self.start_chat()
        self.enter(self.employer)
        self.client.post(reverse('conversation_start', args=['services', self.service.pk]))
        self.assertEqual(Conversation.objects.count(), 1)
        self.assertEqual(Conversation.objects.get().pk, chat.pk)
        self.assertEqual(self.client.get('/messages/').status_code, 200)

    def test_chat_private_messages_and_read_receipt(self):
        chat = self.start_chat()
        url = reverse('conversation', args=[chat.pk])
        self.client.post(url, {'text': '<script>alert(1)</script>'})
        message = Message.objects.get()
        self.assertEqual(Notification.objects.filter(recipient=self.employer).count(), 1)
        self.enter(self.other)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(url, {'text': 'Вмешательство'}).status_code, 404)
        self.assertNotContains(self.client.get('/messages/'), 'script')
        self.enter(self.employer)
        self.assertContains(self.client.get('/messages/'), '1 новых')
        response = self.client.get(url)
        self.assertContains(response, '&lt;script&gt;')
        self.assertNotContains(response, '<script>')
        message.refresh_from_db()
        self.assertTrue(message.is_read)
        self.client.post(url, {'text': 'Добрый день!'})
        self.assertEqual(Message.objects.count(), 2)

    def test_chat_validates_length_and_context_permissions(self):
        chat = self.start_chat()
        self.client.post(reverse('conversation', args=[chat.pk]), {'text': 'x' * 5001})
        self.assertEqual(Message.objects.count(), 0)
        self.assertEqual(self.client.get(reverse('conversation_start', args=['vacancies', self.vacancy.pk])).status_code, 405)
        self.assertEqual(self.client.post(reverse('conversation_start', args=['resumes', self.resume.pk])).status_code, 403)

    def test_incoming_order_allows_worker_to_contact_customer(self):
        order = self.make_order()
        self.enter(self.worker)
        self.assertEqual(self.client.post(reverse('conversation_start', args=['orders', order.pk])).status_code, 302)
        self.assertEqual(Conversation.objects.count(), 1)
        self.enter(self.other)
        self.assertEqual(self.client.post(reverse('conversation_start', args=['orders', order.pk])).status_code, 404)

    def test_order_price_snapshot_and_cancellation(self):
        self.enter(self.employer)
        self.client.post(reverse('action', args=['order', self.service.pk]), {'date': self.today})
        order = Order.objects.get()
        self.assertEqual(order.agreed_price, Decimal('5000'))
        Service.objects.filter(pk=self.service.pk).update(price=7000)
        self.assertEqual(Order.objects.get().agreed_price, Decimal('5000'))
        self.transition('order', order, 'cancelled')
        order.refresh_from_db()
        self.assertEqual(order.status, 'cancelled')
        self.enter(self.worker)
        self.transition('order', order, 'accepted')
        order.refresh_from_db()
        self.assertEqual(order.status, 'cancelled')

    def test_worker_rejects_order_but_customer_cannot_complete_it(self):
        order = self.make_order()
        self.enter(self.employer)
        self.assertEqual(self.transition('order', order, 'done').status_code, 404)
        self.enter(self.worker)
        self.transition('order', order, 'rejected')
        order.refresh_from_db()
        self.assertEqual(order.status, 'rejected')
        self.assertEqual(self.client.get(reverse('action', args=['review', order.pk])).status_code, 404)

    def test_confirming_orders_prevents_double_booking_across_services(self):
        first = self.make_order()
        second_service = Service.objects.create(owner=self.worker, title='Другое', description='Описание', price=1000)
        second = self.make_order(service=second_service, customer=self.other)
        self.enter(self.worker)
        self.transition('order', first, 'accepted')
        self.transition('order', second, 'accepted')
        first.refresh_from_db(); second.refresh_from_db()
        self.assertEqual(first.status, 'accepted')
        self.assertEqual(second.status, 'new')
        self.enter(self.employer)
        self.transition('order', first, 'cancelled')
        self.enter(self.worker)
        self.transition('order', second, 'accepted')
        second.refresh_from_db()
        self.assertEqual(second.status, 'accepted')

    def test_manual_busy_day_blocks_confirmation_and_booked_day_is_protected(self):
        Availability.objects.create(worker=self.worker, date=self.today, available=False)
        order = self.make_order()
        self.enter(self.worker)
        self.transition('order', order, 'accepted')
        order.refresh_from_db(); self.assertEqual(order.status, 'new')
        Availability.objects.filter(worker=self.worker).delete()
        self.transition('order', order, 'accepted')
        self.client.post('/availability/', {'date': self.today, 'note': 'Занят'})
        self.assertFalse(Availability.objects.filter(worker=self.worker, available=False).exists())

    def test_rental_uses_peak_not_sum_of_non_overlapping_reservations(self):
        for offset in [0, 2]:
            Rental.objects.create(offer=self.offer, customer=self.company2, count=2, start=self.today+timedelta(days=offset), end=self.today+timedelta(days=offset), status='accepted')
        self.assertEqual(peak_reserved(self.offer, self.today, self.today+timedelta(days=2)), 2)
        rental = Rental.objects.create(offer=self.offer, customer=self.company2, count=1, start=self.today, end=self.today+timedelta(days=2))
        self.enter(self.employer)
        self.transition('rental', rental, 'accepted')
        rental.refresh_from_db(); self.assertEqual(rental.status, 'accepted')

    def test_rental_price_snapshot_total_and_cancel_releases_capacity(self):
        self.enter(self.other)
        self.client.post(reverse('action', args=['rent', self.offer.pk]), {'count': 2, 'start': self.today, 'end': self.today+timedelta(days=2)})
        rental = Rental.objects.get()
        self.assertEqual(rental.agreed_rate, Decimal('2000'))
        self.assertEqual(rental.total_price, Decimal('12000'))
        StaffOffer.objects.filter(pk=self.offer.pk).update(rate=3000)
        rental.refresh_from_db(); self.assertEqual(rental.total_price, Decimal('12000'))
        self.enter(self.employer)
        self.transition('rental', rental, 'accepted')
        self.enter(self.other)
        self.transition('rental', rental, 'cancelled')
        rental.refresh_from_db(); self.assertEqual(rental.status, 'cancelled')
        self.assertEqual(peak_reserved(self.offer, self.today, self.offer.end), 0)
        self.enter(self.employer)
        self.transition('rental', rental, 'accepted')
        rental.refresh_from_db(); self.assertEqual(rental.status, 'cancelled')

    def test_application_withdraw_and_resubmit_and_hire(self):
        application = Application.objects.create(vacancy=self.vacancy, worker=self.worker)
        self.enter(self.worker)
        self.transition('application', application, 'withdrawn')
        application.refresh_from_db(); self.assertEqual(application.status, 'withdrawn')
        self.enter(self.employer)
        self.transition('application', application, 'invited')
        application.refresh_from_db(); self.assertEqual(application.status, 'withdrawn')
        self.enter(self.worker)
        self.client.post(reverse('action', args=['apply', self.vacancy.pk]), {'message': 'Снова готов'})
        application.refresh_from_db(); self.assertEqual(application.status, 'review')
        self.assertEqual(Application.objects.count(), 1)
        self.enter(self.employer)
        self.transition('application', application, 'hired')
        self.enter(self.worker)
        self.transition('application', application, 'withdrawn')
        application.refresh_from_db(); self.assertEqual(application.status, 'hired')

    def test_invitation_response_and_permissions(self):
        invitation = Invitation.objects.create(company=self.company, worker=self.worker, message='Приходите')
        self.enter(self.other)
        self.assertEqual(self.transition('invitation', invitation, 'accepted').status_code, 404)
        self.enter(self.worker)
        self.transition('invitation', invitation, 'accepted')
        self.transition('invitation', invitation, 'declined')
        invitation.refresh_from_db(); self.assertEqual(invitation.status, 'accepted')
        self.assertTrue(Notification.objects.filter(recipient=self.employer).exists())

    def test_portfolio_crud_and_owner_protection(self):
        self.enter(self.worker)
        self.client.post(reverse('create', args=['portfolio']), {'title': 'Проект', 'description': 'Моя работа', 'url': 'https://example.com/work'})
        project = PortfolioProject.objects.get()
        self.assertContains(self.client.get('/dashboard/'), 'Моя работа')
        self.enter(self.employer)
        self.assertContains(self.client.get(reverse('detail', args=['resumes', self.resume.pk])), 'Моя работа')
        self.assertEqual(self.client.get(reverse('edit', args=['portfolio', project.pk])).status_code, 403)
        self.enter(self.worker)
        self.client.post(reverse('edit', args=['portfolio', project.pk]), {'title': 'Обновлено', 'description': 'Текст', 'url': 'javascript:alert(1)'})
        project.refresh_from_db(); self.assertEqual(project.title, 'Проект')
        self.client.post(reverse('delete', args=['portfolio', project.pk]))
        self.assertFalse(PortfolioProject.objects.exists())

    def test_account_and_password_change(self):
        self.enter(self.worker)
        self.client.post('/account/', {'first_name': 'Новое имя', 'last_name': 'Фамилия'})
        self.worker.refresh_from_db(); self.assertEqual(self.worker.first_name, 'Новое имя')
        self.assertEqual(self.client.get('/accounts/password_change/').status_code, 200)
        response = self.client.post('/accounts/password_change/', {'old_password': 'StrongPass123!', 'new_password1': 'AnotherSecurePass735!', 'new_password2': 'AnotherSecurePass735!'})
        self.assertRedirects(response, '/accounts/password_change/done/')
        self.worker.refresh_from_db(); self.assertTrue(self.worker.check_password('AnotherSecurePass735!'))

    def test_exports_are_scoped_and_csv_formula_is_escaped(self):
        Application.objects.create(vacancy=self.vacancy, worker=self.worker, message='=IMPORTXML("bad")')
        self.enter(self.other)
        self.assertNotIn('IMPORTXML', self.client.get('/export/applications.csv').content.decode('utf-8'))
        self.enter(self.employer)
        text = self.client.get('/export/applications.csv').content.decode('utf-8')
        self.assertIn("'=IMPORTXML", text)
        self.enter(self.worker)
        self.assertEqual(self.client.get('/export/applications.csv').status_code, 403)

    def test_ics_export_scoping_escaping_and_line_folding(self):
        self.make_order(status='accepted', comment='Текст, перенос\nBEGIN:VEVENT')
        Availability.objects.create(worker=self.worker, date=self.today, note='Длинный текст ' * 30)
        self.enter(self.worker)
        response = self.client.get('/export/calendar.ics')
        text = response.content.decode('utf-8')
        self.assertEqual(response['Content-Type'], 'text/calendar; charset=utf-8')
        self.assertEqual(text.count('\r\nBEGIN:VEVENT'), 2)
        self.assertIn('\\nBEGIN:VEVENT', text)
        self.assertTrue(all(len(line.encode('utf-8')) <= 75 for line in text.split('\r\n')))
        self.enter(self.employer)
        self.assertEqual(self.client.get('/export/calendar.ics').status_code, 403)

    def test_new_pages_render_with_data(self):
        order = self.make_order(status='done')
        Review.objects.create(order=order, rating=5, text='Хорошо')
        Rental.objects.create(offer=self.offer, customer=self.company2, count=1, start=self.today, end=self.today, agreed_rate=2000)
        Invitation.objects.create(company=self.company, worker=self.worker, message='Приглашение')
        PortfolioProject.objects.create(owner=self.worker, title='Проект', description='Пример')
        for user in [self.employer, self.other, self.worker]:
            self.enter(user)
            for path in ['/dashboard/', '/favorites/', '/notifications/', '/messages/', '/account/']:
                self.assertEqual(self.client.get(path).status_code, 200, path)

    def test_csrf_protects_new_mutations(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.worker)
        for url in [reverse('favorite_toggle', args=['vacancies', self.vacancy.pk]), reverse('conversation_start', args=['vacancies', self.vacancy.pk]), '/notifications/read-all/']:
            self.assertEqual(client.post(url).status_code, 403)

    def test_portfolio_attachment_upload_and_private_download(self):
        with TemporaryDirectory() as directory, override_settings(MEDIA_ROOT=directory):
            self.enter(self.worker)
            upload = SimpleUploadedFile('example.pdf', b'%PDF-1.7\nDemo portfolio', content_type='application/pdf')
            self.client.post(reverse('create', args=['portfolio']), {'title': 'Материал', 'description': 'Описание', 'attachment': upload})
            project = PortfolioProject.objects.get()
            self.assertTrue(project.attachment.name.endswith('.pdf'))
            self.assertNotIn('example.pdf', project.attachment.name)
            self.assertEqual(self.client.get(reverse('edit', args=['portfolio', project.pk])).status_code, 200)
            url = reverse('portfolio_download', args=[project.pk])
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertIn('attachment;', response['Content-Disposition'])
            self.assertEqual(b''.join(response.streaming_content), b'%PDF-1.7\nDemo portfolio')
            self.enter(self.employer)
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            response.close()
            second = User.objects.create_user(username='second', email='second@example.com', role='worker', password='StrongPass123!')
            self.enter(second)
            self.assertEqual(self.client.get(url).status_code, 403)
            self.client.logout()
            self.assertEqual(self.client.get(url).status_code, 302)

    def test_portfolio_rejects_disguised_and_oversized_files(self):
        with TemporaryDirectory() as directory, override_settings(MEDIA_ROOT=directory):
            self.enter(self.worker)
            for upload in [SimpleUploadedFile('attack.pdf', b'<html>unsafe</html>'), SimpleUploadedFile('image.svg', b'<svg></svg>'), SimpleUploadedFile('huge.pdf', b'%PDF-' + b'a' * (10 * 1024 * 1024))]:
                self.client.post(reverse('create', args=['portfolio']), {'title': 'Файл', 'description': 'Описание', 'attachment': upload})
                self.assertFalse(PortfolioProject.objects.exists())

    def test_private_attachment_respects_hidden_profile_without_public_services(self):
        with TemporaryDirectory() as directory, override_settings(MEDIA_ROOT=directory):
            Service.objects.filter(owner=self.worker).update(is_active=False)
            self.resume.is_visible = False
            self.resume.save()
            project = PortfolioProject.objects.create(owner=self.worker, title='Закрыто', description='Текст', attachment=SimpleUploadedFile('work.pdf', b'%PDF-1.7 test'))
            self.enter(self.employer)
            self.assertEqual(self.client.get(reverse('portfolio_download', args=[project.pk])).status_code, 404)
            Application.objects.create(vacancy=self.vacancy, worker=self.worker)
            response = self.client.get(reverse('portfolio_download', args=[project.pk]))
            self.assertEqual(response.status_code, 200)
            response.close()

    def test_demo_seed_is_idempotent(self):
        output = StringIO()
        call_command('seed_demo', stdout=output)
        models = [User, Vacancy, Service, Application, Order, Review, Rental, Conversation, Message, Notification, PortfolioProject]
        counts = [model.objects.count() for model in models]
        user = User.objects.get(email='design@example.com')
        user.set_password('KeepExistingPassword!')
        user.save()
        call_command('seed_demo', stdout=output)
        self.assertEqual(counts, [model.objects.count() for model in models])
        user.refresh_from_db()
        self.assertTrue(user.check_password('KeepExistingPassword!'))

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_password_reset_email_and_single_use_token(self):
        from django.core import mail
        from urllib.parse import urlsplit
        import re
        response = self.client.post('/accounts/password_reset/', {'email': 'WORKER@EXAMPLE.COM'})
        self.assertRedirects(response, '/accounts/password_reset/done/')
        self.assertEqual(len(mail.outbox), 1)
        link = re.search(r'https?://[^\s]+', mail.outbox[0].body).group(0)
        path = urlsplit(link).path
        response = self.client.get(path)
        self.assertEqual(response.status_code, 302)
        confirm_path = response.url
        self.assertEqual(self.client.get(confirm_path).status_code, 200)
        response = self.client.post(confirm_path, {'new_password1': 'RestoredSecurePassword468!', 'new_password2': 'RestoredSecurePassword468!'})
        self.assertRedirects(response, '/accounts/reset/done/')
        self.worker.refresh_from_db()
        self.assertTrue(self.worker.check_password('RestoredSecurePassword468!'))
        self.assertContains(self.client.get(path), 'Ссылка недействительна')
        self.client.post('/accounts/password_reset/', {'email': 'unknown@example.com'})
        self.assertEqual(len(mail.outbox), 1)

    def test_dashboard_paginates_sections_independently(self):
        for index in range(13):
            self.make_order(comment=f'Заказ {index}')
        self.enter(self.employer)
        response = self.client.get('/dashboard/')
        self.assertEqual(len(response.context['orders']), 10)
        self.assertEqual(response.context['stats']['orders'], 13)
        self.assertContains(response, 'orders_page=2#orders')
        response = self.client.get('/dashboard/?orders_page=2&application_status=invited')
        self.assertEqual(len(response.context['orders']), 3)
        self.assertEqual(response.context['orders'].number, 2)
        self.assertIn('application_status=invited', response.context['orders'].query_string)

    def test_order_creation_rejects_known_busy_dates(self):
        Availability.objects.create(worker=self.worker, date=self.today, available=False)
        self.enter(self.employer)
        response = self.client.post(reverse('action', args=['order', self.service.pk]), {'date': self.today})
        self.assertContains(response, 'Исполнитель занят')
        self.assertFalse(Order.objects.exists())

    def test_worker_can_preview_own_resume_but_not_another(self):
        self.enter(self.worker)
        self.assertContains(self.client.get(reverse('detail', args=['resumes', self.resume.pk])), 'Так работодатели видят ваше резюме')
        second = User.objects.create_user(username='preview', email='preview@example.com', role='worker')
        self.enter(second)
        self.assertEqual(self.client.get(reverse('detail', args=['resumes', self.resume.pk])).status_code, 404)

    def test_employer_registration_link_preselects_role(self):
        response = self.client.get('/register/?role=employer')
        self.assertEqual(response.context['form'].initial['role'], 'employer')
        response = self.client.get('/register/?role=admin')
        self.assertEqual(response.context['form'].initial['role'], 'worker')

    def test_admin_pages_include_new_entities(self):
        admin = User.objects.create_superuser(username='admin', email='admin@example.com', password='StrongPass123!', role='employer')
        self.enter(admin)
        for name in ['user', 'vacancy', 'service', 'order', 'rental', 'notification', 'conversation', 'message', 'portfolioproject', 'favorite']:
            self.assertEqual(self.client.get(f'/admin/marketplace/{name}/').status_code, 200)
        project = PortfolioProject.objects.create(owner=self.worker, title='Админка', description='Проверка')
        self.assertEqual(self.client.get(f'/admin/marketplace/portfolioproject/{project.pk}/change/').status_code, 200)

    def test_rating_sort_keeps_unreviewed_services_last(self):
        order = self.make_order(status='done')
        Review.objects.create(order=order, rating=5, text='Отлично')
        Service.objects.create(owner=self.worker, title='Без отзывов', description='Описание', price=1000)
        response = self.client.get('/catalog/services/?sort=rating')
        self.assertEqual(response.context['items'][0].pk, self.service.pk)
