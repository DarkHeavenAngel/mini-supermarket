from django.contrib import admin
from django.contrib.auth.models import Group
from .models import (Employee, CustomerCard, Check, Category, Product, StoreProduct, Sale)
from decimal import Decimal

"""
нагадую, що всі методи для обчислення, які я тут прописую (або в моделях) потрібні лише для адмінки, щоб було зручно тестувати
все це не виконує вимог і треба буде окремо прописувати код з запитами на обчислення і тд у в'юсі
"""

class SaleInline(admin.TabularInline):
    model = Sale
    extra = 1
    autocomplete_fields = ['upc']
    readonly_fields = ('display_selling_price',)

    # для правильного відображення ціни
    @admin.display(description='Ціна')
    def display_selling_price(self, obj):
        if obj and obj.selling_price:
            return f"{obj.selling_price:.2f}".replace('.', ',')
        return "0,00"

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('category_number', 'category_name')
    search_fields = ('category_name',)
    ordering = ('category_name',)

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('id_product', 'product_name', 'get_category_name', 'manufacturer')
    list_filter = ('category_number',)
    search_fields = ('product_name', 'manufacturer')
    autocomplete_fields = ['category_number']
    ordering = ('product_name',)

    @admin.display(description='Категорія', ordering='category_number__category_name')
    def get_category_name(self, obj):
        return obj.category_number.category_name

@admin.register(StoreProduct)
class StoreProductAdmin(admin.ModelAdmin):
    list_display = ('upc', 'get_product_name', 'display_selling_price', 'products_number', 'promotional_product')
    list_filter = ('promotional_product', 'id_product__category_number')
    search_fields = ('upc', 'id_product__product_name')
    autocomplete_fields = ['id_product', 'upc_prom']
    ordering = ('id_product__product_name',)

    # метод для автоматичної зміни методу на читання
    def get_readonly_fields(self, request, obj=None):
        if obj and obj.promotional_product:
            return self.readonly_fields + ('display_selling_price',)
        return self.readonly_fields

    @admin.display(description='Назва продукту', ordering='id_product__product_name')
    def get_product_name(self, obj):
        return obj.id_product.product_name

    # для правильного відображення ціни
    @admin.display(description='Ціна', ordering='selling_price')
    def display_selling_price(self, obj):
        if obj and obj.selling_price:
            return f"{obj.selling_price:.2f}".replace('.', ',')
        return "0,00"

@admin.register(CustomerCard)
class CustomerCardAdmin(admin.ModelAdmin):
    list_display = ('card_number', 'get_full_name', 'phone_number', 'percent')
    list_filter = ('percent', 'city')
    search_fields = ('card_number', 'cust_surname', 'cust_name', 'phone_number')
    ordering = ('cust_surname', 'cust_name',)

    @admin.display(description='ПІБ клієнта', ordering='cust_surname')
    def get_full_name(self, obj):
        if obj.cust_patronymic:
            return f"{obj.cust_surname} {obj.cust_name} {obj.cust_patronymic}"
        return f"{obj.cust_surname} {obj.cust_name}"

@admin.register(Check)
class CheckAdmin(admin.ModelAdmin):
    list_display = ('check_number', 'get_employee_name', 'get_customer_name', 'print_date', 'display_sum_total')
    list_filter = ('print_date', 'id_employee')
    search_fields = ('check_number', 'id_employee__empl_surname', 'card_number__card_number')
    autocomplete_fields = ['id_employee', 'card_number']
    inlines = [SaleInline]
    date_hierarchy = 'print_date'
    readonly_fields = ['display_sum_total', 'display_vat', 'check_number', 'print_date']

    # метод для автоматичної зміни методу на читання (блок вибору працівника для касира)
    def get_readonly_fields(self, request, obj=None):
        if request.user.is_superuser or request.user.empl_role == 'Менеджер':
            return self.readonly_fields
        return list(self.readonly_fields) + ['id_employee']

    # фільтрація списку чеків залежно від ролі (касир бачить тільки свої чеки)
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser or request.user.empl_role == 'Менеджер':
            return qs
        return qs.filter(id_employee=request.user)

    # система сама підставляє касира, який створив чек
    def save_model(self, request, obj, form, change):
        if getattr(obj, 'id_employee', None) is None:
            obj.id_employee = request.user
        super().save_model(request, obj, form, change)

    # автоматичний підрахунок пдв та суми
    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        check = form.instance
        total = sum(sale.selling_price * sale.product_number for sale in check.sale_set.all())

        if check.card_number:
            discount = Decimal(check.card_number.percent) / Decimal('100')
            total = total * (Decimal('1') - discount)

        check.sum_total = total
        check.vat = total * Decimal('0.2')
        check.save()

    # для правильного відображення ціни
    @admin.display(description='Сума', ordering='sum_total')
    def display_sum_total(self, obj):
        if obj and obj.sum_total:
            return f"{obj.sum_total:.2f}".replace('.', ',')
        return "0,00"

    # для правильного відображення ціни
    @admin.display(description='ПДВ', ordering='vat')
    def display_vat(self, obj):
        if obj and obj.vat:
            return f"{obj.vat:.2f}".replace('.', ',')
        return "0,00"

    @admin.display(description='Працівник', ordering='id_employee__empl_surname')
    def get_employee_name(self, obj):
        return f"{obj.id_employee.empl_surname} {obj.id_employee.empl_name}"

    @admin.display(description='Клієнт', ordering='card_number__cust_surname')
    def get_customer_name(self, obj):
        if obj.card_number:
            return f"{obj.card_number.cust_surname} {obj.card_number.cust_name}"
        return "-"

@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ('id_employee', 'get_full_name', 'empl_role', 'phone_number', 'city', 'is_active')
    list_filter = ('is_active', 'empl_role', 'city')
    search_fields = ('id_employee', 'empl_surname', 'empl_name', 'phone_number')
    ordering = ('empl_surname', 'empl_name',)

    fieldsets = (
        ('Авторизація', {'fields': ('id_employee', 'password')}),
        ('Персональні дані', {'fields': ('empl_surname', 'empl_name', 'empl_patronymic', 'date_of_birth')}),
        ('Контакти', {'fields': ('phone_number', 'city', 'street', 'zip_code')}),
        ('Робоча інформація', {'fields': ('empl_role', 'salary', 'date_of_start')}),
        ('Дозволи', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
    )

    @admin.display(description='ПІБ Працівника', ordering='empl_surname')
    def get_full_name(self, obj):
        if obj.empl_patronymic:
            return f"{obj.empl_surname} {obj.empl_name} {obj.empl_patronymic}"
        return f"{obj.empl_surname} {obj.empl_name}"

    # хешування пароля при зміні або створені працівника
    def save_model(self, request, obj: Employee, form, change):
        if obj.password and not obj.password.startswith('pbkdf2_'):
            obj.set_password(obj.password)
        super().save_model(request, obj, form, change)

