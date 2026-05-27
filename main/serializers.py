from rest_framework import serializers
from .models import Employee, Product, Category, StoreProduct, CustomerCard, Check, Sale


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ['category_number', 'category_name']

class ProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = ['id_product', 'category_number', 'product_name', 'characteristics', 'manufacturer']

class StoreProductSerializer(serializers.ModelSerializer):
    upc_prom = serializers.PrimaryKeyRelatedField(queryset = StoreProduct.objects.all(), required = False, allow_null = True)
    class Meta:
        model = StoreProduct
        fields = ['upc', 'upc_prom', 'id_product', 'selling_price', 'products_number', 'promotional_product']

class EmployeeSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=True, style={'input_type': 'password'})
    class Meta:
        model = Employee
        fields = ['id_employee', 'empl_surname', 'empl_name', 'empl_patronymic',
                  'empl_role', 'salary', 'date_of_birth', 'date_of_start',
                  'phone_number', 'city', 'street', 'zip_code', 'password']

    def create(self, validated_data):
        password = validated_data.pop('password')
        user = Employee.objects.create_user(password=password, **validated_data)
        return user

class CustomerCardSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomerCard
        fields = ['card_number', 'cust_surname', 'cust_name', 'cust_patronymic',
                  'phone_number', 'city', 'street', 'zip_code', 'percent']

class CheckSerializer(serializers.ModelSerializer):
    class Meta:
        model = Check
        fields = ['check_number', 'id_employee', 'card_number', 'print_date', 'sum_total', 'vat']
        read_only_fields = ['print_date', 'sum_total', 'vat']

class SaleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Sale
        fields = ['upc', 'check_number', 'product_number', 'selling_price']
        read_only_fields = ['selling_price']


