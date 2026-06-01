from django.urls import path
from main.views import EmployeeListAPIView, EmployeeDetailAPIView, CategoryListAPIView, CategoryDetailAPIView, \
    ProductListAPIView, ProductDetailAPIView, EmployeeProfileAPIView, DashboardStatsAPIView, CustomerCardListAPIView, \
    CustomerCardDetailAPIView, CheckListAPIView, CheckDetailAPIView, StoreProductListAPIView

urlpatterns = [
    path('employees/', EmployeeListAPIView.as_view(), name='employee-list'),
    path('employees/<str:id_employee>/', EmployeeDetailAPIView.as_view(), name='employee-detail'),
    path('categories/', CategoryListAPIView.as_view(), name='category-list'),
    path('categories/<int:category_number>/', CategoryDetailAPIView.as_view(), name='category-detail'),
    path('products/', ProductListAPIView.as_view(), name='product-list'),
    path('products/<int:id_product>/', ProductDetailAPIView.as_view(), name='product-detail'),
    path('profile/', EmployeeProfileAPIView.as_view(), name='employee-profile'),
    path('dashboard/stats/', DashboardStatsAPIView.as_view(), name='dashboard-stats'),
    path('customers/', CustomerCardListAPIView.as_view(), name='customer-card-list'),
    path('customers/<str:customer_card>/', CustomerCardDetailAPIView.as_view(), name='customer-card-detail'),
    path('checks/', CheckListAPIView.as_view(), name='check-list'),
    path('checks/<str:check>/', CheckDetailAPIView.as_view(), name='check-detail'),
    path('store_products/', StoreProductListAPIView.as_view(), name='store-product-list'),
    path('store_products/<str:store_product_id>/', StoreProductListAPIView.as_view(), name='store-product-detail')
]

