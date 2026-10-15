from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import *
@admin.register(User)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (('Роль', {'fields': ('role',)}),)
    add_fieldsets = UserAdmin.add_fieldsets + (('Профиль', {'fields': ('email', 'role')}),)
    list_display = ['email', 'role', 'is_staff']
admin.site.register([Company, Resume, Vacancy, Application, Invitation, Service, Order, Review, Availability, StaffOffer, Rental])
admin.site.site_header = 'Смена · управление платформой'
