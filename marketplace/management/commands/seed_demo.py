from datetime import timedelta
from django.core.management.base import BaseCommand
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from marketplace.models import (User, Company, Resume, Vacancy, Service, Availability,
                                StaffOffer, PortfolioProject, Order, Review, Rental,
                                Application, Invitation, Favorite, Conversation, Message, Notification)


class Command(BaseCommand):
    help = 'Создать демонстрационные профили, публикации и рабочие сценарии. Пароль: DemoStaff2026!'

    @transaction.atomic
    def handle(self, *args, **options):
        def account(email, role, first, last=''):
            user, created = User.objects.get_or_create(email=email, defaults={
                'username': email, 'role': role, 'first_name': first, 'last_name': last,
            })
            if created:
                user.set_password('DemoStaff2026!')
                user.save()
            return user

        def enrich(obj, **values):
            changed = []
            for field, value in values.items():
                if getattr(obj, field) in ('', None, 'other'):
                    setattr(obj, field, value)
                    changed.append(field)
            if changed:
                obj.save(update_fields=changed)
            return obj

        employer = account('company@example.com', 'employer', 'Алексей')
        partner = account('partner@example.com', 'employer', 'Мария')
        worker = account('worker@example.com', 'worker', 'Анна', 'Смирнова')
        designer = account('design@example.com', 'worker', 'Михаил', 'Орлов')
        company, _ = Company.objects.get_or_create(owner=employer, defaults={
            'name': 'Лист & кофе', 'industry': 'Рестораны и гостеприимство',
            'description': 'Городские кофейни с заботой о гостях и команде. Ищем людей, которые любят своё дело.',
            'contacts': 'company@example.com',
        })
        partner_company, _ = Company.objects.get_or_create(owner=partner, defaults={
            'name': 'Точка роста', 'industry': 'События и логистика',
            'description': 'Помогаем бизнесу организовывать события и собирать команды.', 'contacts': 'partner@example.com',
        })
        enrich(company, city='Казань')
        enrich(partner_company, city='Санкт-Петербург')
        resumes = {}
        for person, spec, skills, city in [
            (worker, 'Бариста и организатор мероприятий', 'Приготовление кофе, сервис, организация мероприятий', 'Казань'),
            (designer, 'Графический дизайнер', 'Figma, айдентика, типографика', 'Санкт-Петербург'),
        ]:
            resume, _ = Resume.objects.get_or_create(owner=person, defaults={
                'specialization': spec, 'skills': skills, 'experience': 'Более трёх лет работы с частными клиентами и компаниями.',
                'contacts': person.email, 'portfolio': 'Примеры проектов предоставлю при знакомстве.',
            })
            enrich(resume, city=city, desired_salary=65000)
            resumes[person.pk] = resume
        vacancies = []
        for c, title, salary, kind, fmt, category in [
            (company, 'Бариста в уютную кофейню', 3500, 'day', 'Очно · смена 8 часов', 'hospitality'),
            (partner_company, 'Помощник на мероприятие', 4000, 'day', 'Очно · гибкий график', 'events'),
            (partner_company, 'Менеджер проектов', 85000, 'permanent', 'Гибрид · полный день', 'events'),
            (company, 'Администратор кофейни', 65000, 'permanent', 'Очно · график 2/2', 'hospitality'),
        ]:
            vacancy, _ = Vacancy.objects.get_or_create(company=c, title=title, defaults={
                'salary': salary, 'kind': kind, 'format': fmt,
                'requirements': 'Ответственность, внимание к деталям и желание работать в команде. Опыт приветствуется. Обучаем и поддерживаем на каждом этапе.',
            })
            enrich(vacancy, category=category, city=c.city)
            vacancies.append(vacancy)
        services = []
        for owner, title, price, category, description in [
            (worker, 'Кофейный кейтеринг', 8000, 'hospitality', 'Кофейная станция для вашего события. Подберём меню и позаботимся о каждом госте.'),
            (designer, 'Логотип для вашего бренда', 12000, 'creative', 'Разработаю фирменный знак: бриф, три концепции и подготовка исходников.'),
            (worker, 'Помощь в организации события', 5000, 'events', 'Координация гостей, подрядчиков и расписания в день мероприятия.'),
        ]:
            service, _ = Service.objects.get_or_create(owner=owner, title=title, defaults={'price': price, 'description': description})
            enrich(service, category=category, city=resumes[owner.pk].city)
            services.append(service)
        today = timezone.localdate()
        offers = []
        for c, spec, count, rate, category in [
            (company, 'Бариста', 3, 3500, 'hospitality'),
            (partner_company, 'Персонал для мероприятий', 8, 3000, 'events'),
        ]:
            offer, _ = StaffOffer.objects.get_or_create(company=c, specialty=spec, defaults={
                'count': count, 'rate': rate, 'start': today, 'end': today+timedelta(days=60),
                'description': 'Опытные сотрудники для усиления вашей команды. Условия и задачи обсудим перед подтверждением.',
            })
            enrich(offer, category=category, city=c.city)
            offers.append(offer)
        for offset in [1, 3, 5, 7]:
            Availability.objects.get_or_create(worker=worker, date=today+timedelta(days=offset), defaults={'available': True, 'note': 'Готова к новой смене'})
        PortfolioProject.objects.get_or_create(owner=worker, title='Кофейная станция на городском фестивале', defaults={
            'description': 'Организация кофейной зоны на 200 гостей: меню, подготовка станции и координация команды.',
        })
        PortfolioProject.objects.get_or_create(owner=designer, title='Айдентика локальной кофейни', defaults={
            'description': 'Концепция логотипа, палитра, упаковка и макеты меню. Пример проекта для демонстрационного профиля.',
        })
        Application.objects.get_or_create(vacancy=vacancies[0], worker=worker, defaults={'message': 'Есть опыт работы в кофейне. Готова обсудить смену.'})
        Invitation.objects.get_or_create(company=company, worker=worker, message='Анна, приглашаем познакомиться с нашей командой. Удобное время можно обсудить в переписке.')
        # Stable demo markers keep repeated invocations idempotent even on another day.
        Order.objects.get_or_create(service=services[0], customer=partner, comment='Демо: кофе для встречи команды', defaults={
            'date': today+timedelta(days=2), 'agreed_price': services[0].price,
        })
        completed, _ = Order.objects.get_or_create(service=services[1], customer=employer, comment='Демо: айдентика новой кофейни', defaults={
            'date': today-timedelta(days=3), 'agreed_price': services[1].price, 'status': 'done',
        })
        Review.objects.get_or_create(order=completed, defaults={'rating': 5, 'text': 'Демонстрационный отзыв: всё готово в срок, исходники переданы.'})
        Rental.objects.get_or_create(offer=offers[0], customer=partner_company, message='Демо: команда для выездного мероприятия', defaults={
            'count': 1, 'start': today+timedelta(days=7), 'end': today+timedelta(days=9), 'agreed_rate': offers[0].rate,
        })
        Favorite.objects.get_or_create(user=worker, vacancy=vacancies[1])
        Favorite.objects.get_or_create(user=employer, service=services[1])
        a, b = sorted([employer.pk, worker.pk])
        chat, _ = Conversation.objects.get_or_create(participant_a_id=a, participant_b_id=b, defaults={'subject': 'Знакомство с командой кофейни'})
        Message.objects.get_or_create(conversation=chat, sender=employer, text='Анна, добрый день! Расскажите, какие смены вам удобны?')
        for recipient, title, text, url in [
            (worker, 'Приглашение от «Лист & кофе»', 'Обсудите знакомство с командой в личном кабинете.', reverse('dashboard')),
            (employer, 'Новый отклик на вакансию бариста', 'Анна Смирнова готова обсудить смену.', reverse('dashboard')),
            (worker, 'Добро пожаловать в демо Смены', 'Проверьте переписку: работодатель уже написал вам.', reverse('conversation', args=[chat.pk])),
        ]:
            Notification.objects.get_or_create(recipient=recipient, title=title, text=text, defaults={'url': url})
        self.stdout.write(self.style.SUCCESS(
            'Демо готово. company@example.com / partner@example.com / worker@example.com / design@example.com; пароль новых аккаунтов: DemoStaff2026!'
        ))
