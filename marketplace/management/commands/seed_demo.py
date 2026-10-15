from datetime import timedelta
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from marketplace.models import *

class Command(BaseCommand):
    help = 'Создать демонстрационные профили и публикации. Пароль: DemoStaff2026!'
    @transaction.atomic
    def handle(self, *args, **options):
        def account(email, role, first, last=''):
            user, created = User.objects.get_or_create(email=email, defaults={'username': email, 'role': role, 'first_name': first, 'last_name': last})
            if created: user.set_password('DemoStaff2026!'); user.save()
            return user
        employer = account('company@example.com', 'employer', 'Алексей')
        partner = account('partner@example.com', 'employer', 'Мария')
        worker = account('worker@example.com', 'worker', 'Анна', 'Смирнова')
        second_worker = account('design@example.com', 'worker', 'Михаил', 'Орлов')
        company, _ = Company.objects.get_or_create(owner=employer, defaults={'name': 'Лист & кофе', 'industry': 'Рестораны и гостеприимство', 'description': 'Городские кофейни с заботой о гостях и команде. Ищем людей, которые любят своё дело.', 'contacts': 'company@example.com'})
        partner_company, _ = Company.objects.get_or_create(owner=partner, defaults={'name': 'Точка роста', 'industry': 'События и логистика', 'description': 'Помогаем бизнесу организовывать события и собирать команды.', 'contacts': 'partner@example.com'})
        for person, spec, skills in [(worker, 'Бариста и организатор мероприятий', 'Приготовление кофе, сервис, организация мероприятий'), (second_worker, 'Графический дизайнер', 'Figma, айдентика, типографика')]:
            Resume.objects.get_or_create(owner=person, defaults={'specialization': spec, 'skills': skills, 'experience': 'Более трёх лет работы с частными клиентами и компаниями.', 'contacts': person.email, 'portfolio': 'Примеры проектов предоставлю при знакомстве.'})
        for c, title, salary, kind, fmt in [(company, 'Бариста в уютную кофейню', 3500, 'day', 'Очно · смена 8 часов'), (partner_company, 'Помощник на мероприятие', 4000, 'day', 'Очно · гибкий график'), (partner_company, 'Менеджер проектов', 85000, 'permanent', 'Гибрид · полный день'), (company, 'Администратор кофейни', 65000, 'permanent', 'Очно · график 2/2')]:
            Vacancy.objects.get_or_create(company=c, title=title, defaults={'salary': salary, 'kind': kind, 'format': fmt, 'requirements': 'Ответственность, внимание к деталям и желание работать в команде. Опыт приветствуется. Обучаем и поддерживаем на каждом этапе.'})
        for owner, title, price, description in [(worker, 'Кофейный кейтеринг', 8000, 'Кофейная станция для вашего события. Подберём меню и позаботимся о каждом госте.'), (second_worker, 'Логотип для вашего бренда', 12000, 'Разработаю фирменный знак: бриф, три концепции и подготовка исходников.'), (worker, 'Помощь в организации события', 5000, 'Координация гостей, подрядчиков и расписания в день мероприятия.')]:
            Service.objects.get_or_create(owner=owner, title=title, defaults={'price': price, 'description': description})
        today = timezone.localdate()
        for c, spec, count, rate in [(company, 'Бариста', 3, 3500), (partner_company, 'Персонал для мероприятий', 8, 3000)]:
            StaffOffer.objects.get_or_create(company=c, specialty=spec, defaults={'count': count, 'rate': rate, 'start': today, 'end': today+timedelta(days=60), 'description': 'Опытные сотрудники для усиления вашей команды. Условия и задачи обсудим перед подтверждением.'})
        for offset in [1, 3, 5, 7]:
            Availability.objects.get_or_create(worker=worker, date=today+timedelta(days=offset), defaults={'available': True, 'note': 'Готова к новой смене'})
        self.stdout.write(self.style.SUCCESS('Демо готово. company@example.com / partner@example.com / worker@example.com / design@example.com; пароль: DemoStaff2026!'))
