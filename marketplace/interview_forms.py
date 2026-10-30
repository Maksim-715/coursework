from django import forms
from django.utils import timezone
from .models import Interview, PracticeInterview, Vacancy


class InterviewForm(forms.ModelForm):
    class Meta:
        model = Interview
        fields = ['title', 'vacancy', 'starts_at', 'duration', 'format', 'location', 'meeting_url', 'description']
        widgets = {'starts_at': forms.DateTimeInput(format='%Y-%m-%dT%H:%M', attrs={'type': 'datetime-local'})}

    def __init__(self, *args, company, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['vacancy'].queryset = Vacancy.objects.filter(company=company, is_active=True)
        self.fields['starts_at'].help_text = f'Часовой пояс: {timezone.get_current_timezone_name()}.'

    def clean(self):
        data = super().clean()
        if data.get('starts_at') and data['starts_at'] <= timezone.now():
            self.add_error('starts_at', 'Выберите время в будущем.')
        if data.get('format') == Interview.Format.ONLINE and not data.get('meeting_url'):
            self.add_error('meeting_url', 'Укажите ссылку на онлайн-встречу.')
        if data.get('format') in [Interview.Format.OFFICE, Interview.Format.PHONE] and not data.get('location'):
            self.add_error('location', 'Укажите адрес или телефон.')
        return data


class PracticeForm(forms.ModelForm):
    class Meta:
        model = PracticeInterview
        fields = ['topic', 'position']


class ResultForm(forms.Form):
    result = forms.CharField(label='Итоги (видны обоим участникам)', max_length=10000, widget=forms.Textarea)
