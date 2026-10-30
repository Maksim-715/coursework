import csv
from datetime import timedelta
from django.http import HttpResponse
from django.utils import timezone
from .models import Application, Order, Availability, Interview
from django.contrib.auth.decorators import login_required
from .views import role_required


def safe_cell(value):
    value = str(value or '')
    # Prevent spreadsheet formulas when opening user-provided data in Excel.
    return "'" + value if value.lstrip().startswith(('=', '+', '-', '@', '\t', '\r', '\n')) else value


@role_required('employer')
def applications_csv(request):
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="applications.csv"'
    response.write('\ufeff')
    writer = csv.writer(response)
    writer.writerow(['Вакансия', 'Кандидат', 'Email', 'Специализация', 'Статус', 'Дата отклика', 'Письмо'])
    items = Application.objects.filter(vacancy__company__owner=request.user).select_related('vacancy', 'worker__resume').order_by('-created_at')
    for item in items.iterator():
        resume = getattr(item.worker, 'resume', None)
        writer.writerow([safe_cell(value) for value in [item.vacancy.title, item.worker, item.worker.email,
                          resume.specialization if resume else '', item.get_status_display(),
                          item.created_at.strftime('%d.%m.%Y'), item.message]])
    return response


def ical_text(value):
    return str(value).replace('\\', '\\\\').replace('\r', '').replace('\n', '\\n').replace(';', '\\;').replace(',', '\\,')


def folded_line(line):
    """Fold at 75 UTF-8 octets without splitting multibyte characters (RFC 5545)."""
    chunks, part = [], ''
    for char in line:
        if len((part + char).encode('utf-8')) > 75:
            chunks.append(part)
            part = ' '
        part += char
    chunks.append(part)
    return '\r\n'.join(chunks)


@role_required('worker')
def calendar_ics(request):
    today = timezone.localdate()
    limit = today + timedelta(days=366)
    stamp = timezone.now().strftime('%Y%m%dT%H%M%SZ')
    lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//Smena//Availability//RU', 'CALSCALE:GREGORIAN', 'METHOD:PUBLISH', 'X-WR-CALNAME:Моя Смена']
    orders = Order.objects.filter(service__owner=request.user, date__gte=today, date__lte=limit, status__in=['accepted', 'working', 'done']).select_related('service')
    for order in orders:
        lines += ['BEGIN:VEVENT', f'UID:order-{order.pk}-user-{request.user.pk}@smena.local', f'DTSTAMP:{stamp}',
                  f'DTSTART;VALUE=DATE:{order.date:%Y%m%d}', f'DTEND;VALUE=DATE:{order.date+timedelta(days=1):%Y%m%d}',
                  f'SUMMARY:{ical_text(order.service.title)}', f'DESCRIPTION:{ical_text(order.comment)}', 'END:VEVENT']
    for day in Availability.objects.filter(worker=request.user, date__gte=today, date__lte=limit):
        lines += ['BEGIN:VEVENT', f'UID:availability-{day.pk}-user-{request.user.pk}@smena.local', f'DTSTAMP:{stamp}',
                  f'DTSTART;VALUE=DATE:{day.date:%Y%m%d}', f'DTEND;VALUE=DATE:{day.date+timedelta(days=1):%Y%m%d}',
                  f'SUMMARY:{"Готов к работе" if day.available else "Занят"}', f'DESCRIPTION:{ical_text(day.note)}',
                  'TRANSP:TRANSPARENT' if day.available else 'TRANSP:OPAQUE', 'END:VEVENT']
    from .interview_services import participants
    for item in Interview.objects.filter(participants(request.user), status__in=['pending', 'confirmed'], starts_at__date__gte=today, starts_at__date__lte=limit):
        lines += interview_calendar_lines(item, stamp)
    lines.append('END:VCALENDAR')
    response = HttpResponse('\r\n'.join(folded_line(line) for line in lines) + '\r\n', content_type='text/calendar; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="smena-calendar.ics"'
    return response


def interview_calendar_lines(item, stamp):
    from datetime import timezone as datetime_timezone
    return ['BEGIN:VEVENT', f'UID:interview-{item.pk}@smena.local', f'DTSTAMP:{stamp}',
            f'DTSTART:{item.starts_at.astimezone(datetime_timezone.utc):%Y%m%dT%H%M%SZ}',
            f'DTEND:{item.ends_at.astimezone(datetime_timezone.utc):%Y%m%dT%H%M%SZ}',
            f'SUMMARY:{ical_text(item.title)}',
            f'LOCATION:{ical_text(item.meeting_url or item.location)}',
            f'DESCRIPTION:{ical_text(item.description)}',
            f'STATUS:{"CANCELLED" if item.status in ["cancelled", "declined"] else "CONFIRMED" if item.status in ["confirmed", "completed"] else "TENTATIVE"}',
            'END:VEVENT']


@login_required
def interview_ics(request, pk):
    from django.shortcuts import get_object_or_404
    from .models import Interview
    from .interview_services import participants
    item = get_object_or_404(Interview.objects.filter(participants(request.user)), pk=pk)
    lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//Smena//Interviews//RU', 'CALSCALE:GREGORIAN', 'METHOD:PUBLISH']
    lines += interview_calendar_lines(item, timezone.now().strftime('%Y%m%dT%H%M%SZ'))
    lines.append('END:VCALENDAR')
    response = HttpResponse('\r\n'.join(folded_line(line) for line in lines) + '\r\n', content_type='text/calendar; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="interview-{item.pk}.ics"'
    return response
