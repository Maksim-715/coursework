from datetime import timedelta
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from .models import User, Company, Resume, Vacancy, Interview, PracticeInterview, Notification
from .interview_services import schedule, transition


class InterviewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.employer = User.objects.create_user(username='boss', email='boss@example.com', role='employer')
        cls.worker = User.objects.create_user(username='candidate', email='candidate@example.com', role='worker')
        cls.other = User.objects.create_user(username='stranger', email='stranger@example.com', role='employer')
        cls.company = Company.objects.create(owner=cls.employer, name='Компания')
        cls.other_company = Company.objects.create(owner=cls.other, name='Другая')
        cls.resume = Resume.objects.create(owner=cls.worker, specialization='Разработчик')
        cls.vacancy = Vacancy.objects.create(company=cls.company, title='Разработчик', salary=100, kind='permanent')

    def data(self, **kwargs):
        result = {'title': 'Знакомство', 'starts_at': (timezone.now() + timedelta(days=2)).strftime('%Y-%m-%dT%H:%M'),
                  'duration': 60, 'format': 'online', 'meeting_url': 'https://example.com/meeting', 'vacancy': self.vacancy.pk}
        result.update(kwargs)
        return result

    def create_interview(self):
        self.client.force_login(self.employer)
        response = self.client.post(reverse('interview_create', args=[self.resume.pk]), self.data())
        item = Interview.objects.latest('pk')
        self.assertRedirects(response, reverse('interview_detail', args=[item.pk]))
        return item

    def test_schedule_confirm_reschedule_and_cancel(self):
        item = self.create_interview()
        self.assertEqual(item.status, 'pending')
        self.assertTrue(Notification.objects.filter(recipient=self.worker).exists())
        self.client.force_login(self.worker)
        self.client.post(reverse('interview_status', args=[item.pk]), {'status': 'confirmed'})
        item.refresh_from_db()
        self.assertEqual(item.status, 'confirmed')
        self.client.force_login(self.employer)
        self.client.post(reverse('interview_edit', args=[item.pk]), self.data(starts_at=(timezone.now() + timedelta(days=3)).strftime('%Y-%m-%dT%H:%M')))
        item.refresh_from_db()
        self.assertEqual(item.status, 'pending')
        self.client.post(reverse('interview_status', args=[item.pk]), {'status': 'cancelled'})
        item.refresh_from_db()
        self.assertEqual(item.status, 'cancelled')
        self.assertRaises(ValidationError, transition, self.worker, item.pk, 'confirmed')

    def test_overlap_and_adjacent_slots(self):
        item = self.create_interview()
        candidate = Interview(company=self.company, worker=self.worker, title='Пересечение', starts_at=item.starts_at + timedelta(minutes=30), duration=30)
        self.assertRaises(ValidationError, schedule, candidate, self.employer)
        candidate.starts_at = item.ends_at
        schedule(candidate, self.employer)
        # A different employer must also respect the worker's appointments.
        candidate = Interview(company=self.other_company, worker=self.worker, title='Другая компания', starts_at=item.starts_at, duration=60)
        self.assertRaises(ValidationError, schedule, candidate, self.other)
        transition(self.employer, item.pk, 'cancelled')
        schedule(candidate, self.other)

    def test_completion_and_results(self):
        item = self.create_interview()
        self.assertRaises(ValidationError, transition, self.employer, item.pk, 'confirmed')
        transition(self.worker, item.pk, 'confirmed')
        self.assertRaises(ValidationError, transition, self.employer, item.pk, 'completed', 'Хорошо')
        Interview.objects.filter(pk=item.pk).update(starts_at=timezone.now() - timedelta(hours=2))
        transition(self.employer, item.pk, 'completed', 'Следующий этап')
        self.client.force_login(self.worker)
        self.assertContains(self.client.get(reverse('interview_detail', args=[item.pk])), 'Следующий этап')

    def test_privacy_and_post_only_actions(self):
        item = self.create_interview()
        self.assertEqual(self.client.get(reverse('interview_status', args=[item.pk])).status_code, 405)
        self.client.force_login(self.other)
        for route in ['interview_detail', 'interview_edit']:
            self.assertEqual(self.client.get(reverse(route, args=[item.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse('interview_status', args=[item.pk]), {'status': 'cancelled'}).status_code, 404)
        self.assertNotContains(self.client.get(reverse('interviews')), item.title)
        self.client.force_login(self.worker)
        self.assertEqual(self.client.get(reverse('interview_create', args=[self.resume.pk])).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(reverse('interviews')).status_code, 302)

    def test_invalid_schedule_and_hidden_resume(self):
        self.client.force_login(self.employer)
        url = reverse('interview_create', args=[self.resume.pk])
        for changes in [{'starts_at': '2000-01-01T10:00'}, {'duration': 0}, {'duration': 241}, {'meeting_url': ''}, {'format': 'office', 'location': ''}, {'format': 'phone', 'location': ''}]:
            self.assertEqual(self.client.post(url, self.data(**changes)).status_code, 200)
            self.assertFalse(Interview.objects.exists())
        foreign = Vacancy.objects.create(company=self.other_company, title='Чужая', salary=100, kind='day')
        self.client.post(url, self.data(vacancy=foreign.pk))
        self.assertFalse(Interview.objects.exists())
        self.resume.is_visible = False
        self.resume.save()
        self.assertEqual(self.client.get(url).status_code, 404)


class PracticeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.worker = User.objects.create_user(username='worker', email='worker@example.com', role='worker')
        cls.other = User.objects.create_user(username='other', email='other@example.com', role='employer')

    def start(self, topic='general'):
        self.client.force_login(self.worker)
        response = self.client.post(reverse('practice_create'), {'position': 'Разработчик', 'topic': topic})
        item = PracticeInterview.objects.latest('pk')
        self.assertRedirects(response, reverse('practice_detail', args=[item.pk]))
        self.assertEqual(item.answers.count(), 5)
        return item

    def test_draft_completion_and_immutable_history(self):
        item = self.start()
        url = reverse('practice_detail', args=[item.pk])
        first = item.answers.first()
        self.client.post(url, {f'answer_{first.pk}': 'Первый ответ', 'finish': '1'})
        item.refresh_from_db()
        self.assertIsNone(item.completed_at)
        first.refresh_from_db()
        self.assertEqual(first.answer, 'Первый ответ')
        data = {f'answer_{a.pk}': f'Мой пример {a.number}' for a in item.answers.all()}
        self.client.post(url, {**data, 'finish': '1'})
        item.refresh_from_db()
        self.assertIsNotNone(item.completed_at)
        self.assertContains(self.client.get(url), 'Разбор для самопроверки')
        self.client.post(url, {f'answer_{first.pk}': 'Подмена'})
        first.refresh_from_db()
        self.assertEqual(first.answer, 'Мой пример 1')

    def test_topics_privacy_and_validation(self):
        for topic in ['general', 'behavioral', 'it']:
            item = self.start(topic)
            self.assertContains(self.client.get(reverse('practice_history')), 'Разработчик')
        self.client.post(reverse('practice_create'), {'position': '', 'topic': 'unknown'})
        self.assertEqual(PracticeInterview.objects.count(), 3)
        url = reverse('practice_detail', args=[item.pk])
        first = item.answers.first()
        self.client.post(url, {f'answer_{first.pk}': 'a' * 10001})
        first.refresh_from_db()
        self.assertEqual(first.answer, '')
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(url, {'finish': '1'}).status_code, 404)
        self.assertNotContains(self.client.get(reverse('practice_history')), 'Разработчик')
        self.assertRedirects(self.client.post(reverse('practice_create'), {'position': 'Менеджер', 'topic': 'general'}), reverse('practice_detail', args=[PracticeInterview.objects.latest('pk').pk]))


class InterviewIntegrationTests(TestCase):
    setUpTestData = classmethod(InterviewTests.setUpTestData.__func__)
    data = InterviewTests.data
    create_interview = InterviewTests.create_interview

    def test_history_reason_and_noop_edit(self):
        item = self.create_interview()
        self.assertEqual(item.events.count(), 1)
        transition(self.worker, item.pk, 'confirmed')
        count = Notification.objects.count()
        self.client.post(reverse('interview_edit', args=[item.pk]), self.data())
        item.refresh_from_db()
        self.assertEqual(item.status, 'confirmed')
        self.assertEqual(item.events.count(), 2)
        self.assertEqual(Notification.objects.count(), count)
        transition(self.worker, item.pk, 'cancelled', reason='Заболел, нужна другая дата')
        self.assertEqual(item.events.first().detail, 'Заболел, нужна другая дата')
        self.assertContains(self.client.get(reverse('interview_detail', args=[item.pk])), 'Заболел')

    def test_calendar_dashboard_and_conversation_permissions(self):
        item = self.create_interview()
        url = reverse('interview_ics', args=[item.pk])
        content = self.client.get(url).content.decode()
        self.assertIn(f'UID:interview-{item.pk}', content)
        self.assertIn('STATUS:TENTATIVE', content)
        self.assertContains(self.client.get(reverse('dashboard')), item.title)
        self.client.force_login(self.worker)
        self.assertContains(self.client.get(reverse('dashboard'), {'year': item.starts_at.year, 'month': item.starts_at.month}), 'Интервью')
        self.assertContains(self.client.get(reverse('calendar_ics')), f'UID:interview-{item.pk}')
        self.assertEqual(self.client.post(reverse('conversation_start', args=['interviews', item.pk])).status_code, 302)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(reverse('conversation_start', args=['interviews', item.pk])).status_code, 404)

    def test_upcoming_history_and_invitation_entry(self):
        from .models import Invitation
        item = self.create_interview()
        self.assertContains(self.client.get(reverse('interviews')), item.title)
        transition(self.employer, item.pk, 'cancelled')
        self.assertNotContains(self.client.get(reverse('interviews')), item.title)
        self.assertContains(self.client.get(reverse('interviews') + '?tab=history'), item.title)
        invitation = Invitation.objects.create(company=self.company, worker=self.worker, message='Обсудим работу')
        self.resume.is_visible = False
        self.resume.save()
        url = reverse('interview_from_invitation', args=[invitation.pk])
        self.assertContains(self.client.get(url), 'Обсудим работу')
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(url).status_code, 404)


class PracticeNavigationTests(TestCase):
    setUpTestData = classmethod(PracticeTests.setUpTestData.__func__)
    start = PracticeTests.start

    def test_step_saves_preserve_previous_answers(self):
        item = self.start()
        answers = list(item.answers.all())
        url = reverse('practice_detail', args=[item.pk])
        first = answers[0]
        self.assertRedirects(self.client.post(url, {f'answer_{first.pk}': 'Мой первый ответ', 'next': '1'}), url + '?step=2')
        second = answers[1]
        self.client.post(url + '?step=2', {f'answer_{second.pk}': 'Второй ответ', 'next': '1'})
        first.refresh_from_db()
        self.assertEqual(first.answer, 'Мой первый ответ')
        response = self.client.get(url + '?step=2')
        self.assertContains(response, 'Второй ответ')
        self.assertEqual(response.context['answered'], 2)
        self.assertEqual(response.context['progress'], 40)
        self.assertEqual(self.client.get(url + '?step=invalid').context['step'], 1)
        self.assertEqual(self.client.get(url + '?step=999').context['step'], 5)
