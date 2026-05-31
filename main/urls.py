from django.urls import path
from main import views
from main.views import EmployeeListAPIView, EmployeeDetailAPIView, CategoryListAPIView, CategoryDetailAPIView, \
    ProductListAPIView, ProductDetailAPIView, EmployeeProfileAPIView

urlpatterns = [
    path('employees/', EmployeeListAPIView.as_view(), name='employee-list'),
    path('employees/<str:id_employee>/', EmployeeDetailAPIView.as_view(), name='employee-detail'),
    path('categories/', CategoryListAPIView.as_view(), name='category-list'),
    path('categories/<int:category_number>/', CategoryDetailAPIView.as_view(), name='category-detail'),
    path('products/', ProductListAPIView.as_view(), name='product-list'),
    path('products/<int:id_product>/', ProductDetailAPIView.as_view(), name='product-detail'),
    path('profile/', EmployeeProfileAPIView.as_view(), name='employee-profile'),
]

