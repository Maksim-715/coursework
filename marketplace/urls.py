from django.urls import path
from . import views
urlpatterns = [
    path('', views.home, name='home'),
    path('register/', views.register, name='register'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('profile/', views.profile, name='profile'),
    path('catalog/<str:kind>/', views.catalog, name='catalog'),
    path('catalog/<str:kind>/<int:pk>/', views.detail, name='detail'),
    path('create/<str:kind>/', views.edit, name='create'),
    path('edit/<str:kind>/<int:pk>/', views.edit, name='edit'),
    path('delete/<str:kind>/<int:pk>/', views.delete, name='delete'),
    path('action/<str:kind>/<int:pk>/', views.action, name='action'),
    path('status/<str:kind>/<int:pk>/', views.status, name='status'),
    path('availability/', views.availability, name='availability'),
    path('availability/<int:pk>/delete/', views.availability_delete, name='availability_delete'),
]
