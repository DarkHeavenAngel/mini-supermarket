from decimal import Decimal
from django.db import connection, transaction
from datetime import timezone, datetime, date
import re
from rest_framework import viewsets
from .models import Employee, Product, Check, Category, StoreProduct, CustomerCard, Sale
from .serializers import (
    EmployeeSerializer, ProductSerializer, CheckSerializer,
    CategorySerializer, StoreProductSerializer, CustomerCardSerializer, SaleSerializer
)

def store_product(upc, id_product, selling_price, products_number, is_promotional=False, upc_prom=None):
    with connection.cursor() as cursor:
        # перевірка обмеження на кількість запису товару
        cursor.execute("SELECT COUNT(*) FROM StoreProduct WHERE id_product = %s", [id_product])
        count = cursor.fetchone()[0]

        if count >= 2:
            return {
                "success": False,
                "error": 'There is already two records for this product'
            }

        # підрахунок ціни акційного товару
        if is_promotional and upc_prom:
            cursor.execute("SELECT selling_price FROM StoreProduct WHERE upc = %s", [upc_prom])
            row = cursor.fetchone()

            if row:
                normal_price = row[0]
                selling_price = normal_price * Decimal('0.8')
            else:
                return {
                    "success": False,
                    "error": f"Base product {upc_prom} is not promoted"
                }

        cursor.execute("""
            INSERT INTO StoreProduct
            (upc, upc_prom, id_product, selling_price, products_number, promotional_product)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, [upc, upc_prom, id_product, selling_price, products_number, is_promotional])

        return {"success": True, "message": 'Product added successfully'}

def promotional_product(normal_upc, promo_upc, quantity):
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT selling_price, id_product FROM StoreProduct WHERE upc = %s", [normal_upc]
        )
        row = cursor.fetchone()

        if row:
            normal_price = row[0]
            product_id = row[1]

            promo_price = normal_price * Decimal('0.8')

            cursor.execute("""
                INSERT INTO StoreProduct 
                    (upc, upc_prom, id_product, selling_price, products_number, promotional_product)
                    VALUES (%s, %s, %s, %s, %s, True)
                           """, [promo_upc, normal_upc, product_id, promo_price, quantity])

@transaction.atomic
def create_new_check(check_number, id_employee, card_number, items_list):
    with connection.cursor() as cursor:

        # автоматизація номеру чеку
        if not check_number:
            cursor.execute("SELECT MAX(check_number AS INTEGER)) FROM StoreCheck")
            max_check = cursor.fetchone()[0]
            next_number = (max_check or 0) + 1
            check_number = str(next_number).zfill(10)

        # підрахунок суми
        subtotal = Decimal('0.0')
        for item in items_list:
            cursor.execute("SELECT selling_price FROM StoreProduct WHERE upc = %s", [item['upc']])
            row = cursor.fetchone()
            if not row:
                raise ValueError(f"Товар з UPC {item['upc']} не знайдено")
            price = row[0]
            subtotal += price * Decimal(item['qty'])

        # застосування знижки
        discount = Decimal('0.0')
        if card_number:
            cursor.execute("SELECT percent FROM CustomerCard WHERE card_number = %s", [card_number])
            card_row = cursor.fetchone()
            if card_row:
                discount = Decimal(card_row[0])

        multiplier = (Decimal('100') - discount) / Decimal('100')
        final_sum = subtotal * multiplier
        vat_amount = final_sum * Decimal('0.2')

        current_time = timezone.now()

        # створення чеку
        cursor.execute("""
            INSERT INTO StoreCheck (check_number, id_employee, card_number, print_date, sum_total, vat)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, [check_number, id_employee, card_number, current_time, final_sum, vat_amount])

        # додавання та списання товарів
        for item in items_list:
            upc = item['upc']
            qty = item['qty']

            cursor.execute("SELECT selling_price FROM StoreProduct WHERE upc = %s", [item['upc']])
            price = cursor.fetchone()[0]

            cursor.execute("""
                INSERT INTO Sale (upc, check_number, product_number, selling_price)
                VALUES (%s, %s, %s, %s)
            """, [upc, check_number, qty, price])

            # зменшення товару на складі
            cursor.execute("""
                UPDATE StoreProduct 
                SET products_number = products_number - %s
                WHERE UPC = %s
            """, [qty, upc])

    return {"success": True, "message": 'Чек успішно створено'}

def add_new_employee(id_employee, empl_surname, empl_name, empl_role, salary, date_of_birth, date_of_start, phone_number, city, street, zip_code):

    # валідація телефону
    if not re.match(r'^\+380\d{9}$', phone_number):
        return {
            "success": False,
            "error": "Номер телефону повинен починатися з '+380' та містити всього 13 символів"
        }

    # валідація віку
    try:
        if isinstance(date_of_birth, str):
            born_date = datetime.strptime(date_of_birth, "%Y-%m-%d").date()
        else:
            born_date = date_of_birth
    except (ValueError, TypeError):
        return {
            "success": False,
            "error": "Некоректний формат дати народження. Використовуйте РРРР-ММ-ДД"
        }

    today = date.today()
    age = today.year - born_date.year - ((today.month, today.day) < (born_date.month, born_date.day))

    if age < 18:
        return {
            "success": False,
            "error": "Вік працівника не може бути меншим за 18 років"
        }

    # валідація зарплати
    if Decimal(str(salary)) < 0:
        return {
            "success": False,
            "error": "Заробітня плата не може бути від'ємною"
        }

    with connection.cursor() as cursor:
        try:
            cursor.execute("""
                           INSERT INTO Employee 
                           (id_employee, empl_surname, empl_name, empl_role, salary,
                           date_of_birth, date_of_start, phone_number, city, street, zip_code, password, is_active, is_staff, is_superuser)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                           """, [
                id_employee, empl_surname, empl_name, empl_role, salary,
                born_date, date_of_start, phone_number, city, street, zip_code,
                '', True, False, False
            ])
            return {"success": True, "message": "Працівника успішно додано"}

        except Exception as e:
            return {"success": False, "error": f"Помилка бази даних: {str(e)}"}

class EmployeeViewSet(viewsets.ModelViewSet):
    queryset = Employee.objects.all()
    serializer_class = EmployeeSerializer

class ProductViewSet(viewsets.ModelViewSet):
    queryset = Product.objects.all()
    serializer_class = ProductSerializer

class CheckViewSet(viewsets.ModelViewSet):
    queryset = Check.objects.all()
    serializer_class = CheckSerializer

class CategoryViewSet(viewsets.ModelViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer

class StoreProductViewSet(viewsets.ModelViewSet):
    queryset = StoreProduct.objects.all()
    serializer_class = StoreProductSerializer

class CustomerCardViewSet(viewsets.ModelViewSet):
    queryset = CustomerCard.objects.all()
    serializer_class = CustomerCardSerializer

class  SaleViewSet(viewsets.ModelViewSet):
    queryset =  Sale.objects.all()
    serializer_class =  SaleSerializer