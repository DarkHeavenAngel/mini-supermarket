from django.urls import path
from main import views
from main.views import EmployeeListAPIView, EmployeeDetailAPIView

urlpatterns = [
    path('employees/', EmployeeListAPIView.as_view(), name='employee-list'),
    path('employees/<str:id_employee>/', EmployeeDetailAPIView.as_view(), name='employee-detail'),
]