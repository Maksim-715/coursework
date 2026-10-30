"""Visibility rules for catalog items and their historical participants."""
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404
from .models import Vacancy, Service, StaffOffer, Resume

LISTINGS = {'vacancies': Vacancy, 'services': Service, 'staff': StaffOffer, 'resumes': Resume}
FAVORITE_FIELDS = {'vacancies': 'vacancy', 'services': 'service', 'staff': 'staff', 'resumes': 'resume'}


def check_catalog_access(user, kind):
    if kind not in LISTINGS:
        raise Http404
    if kind in ['staff', 'resumes'] and (not user.is_authenticated or user.role != 'employer'):
        raise PermissionDenied


def get_listing(user, kind, pk):
    if kind == 'resumes' and user.is_authenticated and user.role == 'worker':
        return get_object_or_404(Resume, pk=pk, owner=user)
    check_catalog_access(user, kind)
    queryset = LISTINGS[kind].objects.all()
    if kind == 'resumes':
        visible = Q(is_visible=True)
        if user.is_authenticated:
            visible |= Q(owner=user) | Q(owner__application__vacancy__company__owner=user) | Q(owner__invitation__company__owner=user)
    else:
        visible = Q(is_active=True)
        if user.is_authenticated:
            if kind == 'vacancies':
                visible |= Q(company__owner=user) | Q(applications__worker=user)
            elif kind == 'services':
                visible |= Q(owner=user) | Q(orders__customer=user)
            else:
                visible |= Q(company__owner=user) | Q(rental__customer__owner=user)
    return get_object_or_404(queryset.filter(visible).distinct(), pk=pk)
