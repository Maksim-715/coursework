from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.urls import reverse
from django.utils.html import format_html
from .forms import PortfolioForm
from .models import (User, Company, Resume, Vacancy, Application, Invitation, Service,
                     Order, Review, Availability, StaffOffer, Rental, PortfolioProject,
                     Favorite, Notification, Conversation, Message)


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (('Роль', {'fields': ('role',)}),)
    add_fieldsets = UserAdmin.add_fieldsets + (('Профиль', {'fields': ('email', 'role')}),)
    list_display = ['email', 'first_name', 'last_name', 'role', 'is_staff']
    list_filter = ['role', 'is_staff', 'is_active']
    search_fields = ['email', 'first_name', 'last_name']


@admin.action(description='Отправить выбранные публикации в архив')
def archive_selected(modeladmin, request, queryset):
    queryset.update(is_active=False)


@admin.action(description='Восстановить выбранные публикации')
def publish_selected(modeladmin, request, queryset):
    queryset.update(is_active=True)


@admin.register(Vacancy)
class VacancyAdmin(admin.ModelAdmin):
    list_display = ['title', 'company', 'category', 'city', 'salary', 'kind', 'is_active']
    list_filter = ['is_active', 'category', 'kind', 'city']
    search_fields = ['title', 'company__name', 'requirements']
    list_select_related = ['company']
    actions = [archive_selected, publish_selected]


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ['title', 'owner', 'category', 'city', 'price', 'is_active']
    list_filter = ['is_active', 'category', 'city']
    search_fields = ['title', 'owner__email', 'description']
    list_select_related = ['owner']
    actions = [archive_selected, publish_selected]


@admin.register(StaffOffer)
class StaffOfferAdmin(admin.ModelAdmin):
    list_display = ['specialty', 'company', 'count', 'start', 'end', 'rate', 'is_active']
    list_filter = ['is_active', 'category', 'city']
    search_fields = ['specialty', 'company__name']
    actions = [archive_selected, publish_selected]

    def get_readonly_fields(self, request, obj=None):
        if obj and obj.rental_set.filter(status='accepted').exists():
            return ['count', 'start', 'end']
        return []


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ['id', 'service', 'customer', 'date', 'agreed_price', 'status']
    list_filter = ['status', 'date']
    search_fields = ['service__title', 'customer__email']
    readonly_fields = ['agreed_price', 'status']
    list_select_related = ['service', 'customer']

    def has_add_permission(self, request):
        return False

    def get_readonly_fields(self, request, obj=None):
        return ['service', 'customer', 'date', 'agreed_price', 'status']


@admin.register(Rental)
class RentalAdmin(admin.ModelAdmin):
    list_display = ['id', 'offer', 'customer', 'count', 'start', 'end', 'agreed_rate', 'status']
    list_filter = ['status', 'start']
    readonly_fields = ['agreed_rate', 'status']
    list_select_related = ['offer', 'customer']

    def has_add_permission(self, request):
        return False

    def get_readonly_fields(self, request, obj=None):
        return ['offer', 'customer', 'count', 'start', 'end', 'agreed_rate', 'status']


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ['title', 'recipient', 'is_read', 'created_at']
    list_filter = ['is_read', 'created_at']
    search_fields = ['recipient__email', 'title']


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ['name', 'industry', 'city', 'owner']
    search_fields = ['name', 'industry', 'city']


@admin.register(Resume)
class ResumeAdmin(admin.ModelAdmin):
    list_display = ['specialization', 'owner', 'city', 'is_visible']
    list_filter = ['is_visible', 'city']
    search_fields = ['specialization', 'skills', 'owner__email']


@admin.register(Application)
class ApplicationAdmin(admin.ModelAdmin):
    list_display = ['vacancy', 'worker', 'status', 'created_at']
    list_filter = ['status']
    readonly_fields = ['status']
    list_select_related = ['vacancy', 'worker']


@admin.register(PortfolioProject)
class PortfolioProjectAdmin(admin.ModelAdmin):
    form = PortfolioForm
    fields = ['owner', 'title', 'description', 'url', 'attachment', 'download_material']
    readonly_fields = ['download_material']
    list_display = ['title', 'owner', 'created_at']
    search_fields = ['title', 'owner__email']

    @admin.display(description='Материал проекта')
    def download_material(self, obj):
        if obj and obj.attachment:
            return format_html('<a href="{}">Скачать материал</a>', reverse('portfolio_download', args=[obj.pk]))
        return '—'


admin.site.register([Invitation, Review, Availability, Favorite, Conversation, Message])
admin.site.site_header = 'Смена · управление платформой'
admin.site.site_title = 'Смена'
admin.site.index_title = 'Обзор платформы'
