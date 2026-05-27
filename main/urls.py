from django.urls import path
from main import views

urlpatterns = [
    path('api/employees', views.api_employees, name='api_employees'),
]