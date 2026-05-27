import json
from decimal import Decimal

from django.contrib.auth.hashers import make_password
from django.db import connection, transaction, IntegrityError
from datetime import datetime, date

from django.http import JsonResponse
from django.utils import timezone
import re
from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Employee, Product, Check, Category, StoreProduct, CustomerCard, Sale
from .permissions import IsManager, IsCashier
from .serializers import (
    EmployeeSerializer, ProductSerializer, CheckSerializer,
    CategorySerializer, StoreProductSerializer, CustomerCardSerializer, SaleSerializer
)

from django.views.decorators.csrf import csrf_exempt


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

@transaction.atomic
def create_new_check(check_number, id_employee, card_number, items_list):
    with connection.cursor() as cursor:

        # автоматизація номеру чеку
        if not check_number:
            cursor.execute("SELECT MAX(CAST(check_number AS INTEGER)) FROM StoreCheck")
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

#Допоміжна функція для перетворення результатів SQL-запиту в список словників (JSON)
def dictfetchall(cursor):
    columns = [col[0] for col in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]

#CRUD for employees
class EmployeeListAPIView(APIView):
    permission_classes = [IsManager]

    def get(self, request):
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT id_employee, empl_surname, empl_name, empl_patronymic, 
                       empl_role, salary, date_of_birth, date_of_start, 
                       phone_number, city, street, zip_code 
                FROM Employee""")
            employees = dictfetchall(cursor)
        return Response(employees, status=status.HTTP_200_OK)

    def post(self, request):
        data = request.data
        hashed_password = make_password(data.get('password'))

        with connection.cursor() as cursor:
            try:
                cursor.execute("""
                    INSERT INTO Employee (
                        id_employee, password, empl_surname, empl_name, empl_patronymic,
                        empl_role, salary, date_of_birth, date_of_start, phone_number,
                        city, street, zip_code, is_active, is_staff, is_superuser
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, True, False, False)
                """, [
                    data.get('id_employee'), hashed_password, data.get('empl_surname'),
                    data.get('empl_name'), data.get('empl_patronymic'), data.get('empl_role'),
                    data.get('salary'), data.get('date_of_birth'), data.get('date_of_start'),
                    data.get('phone_number'), data.get('city'), data.get('street'), data.get('zip_code')
                ])
                return Response({"message": "Працівника успішно створено"}, status=status.HTTP_201_CREATED)
            except Exception as e:
                return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

class EmployeeDetailAPIView(APIView):
    permission_classes = [IsManager | IsCashier]
    def get(self, request, id_employee):
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT id_employee, empl_surname, empl_name, empl_patronymic, 
                       empl_role, salary, date_of_birth, date_of_start, 
                       phone_number, city, street, zip_code 
                FROM Employee WHERE id_employee = %s
            """, [id_employee])
            row = dictfetchall(cursor)

            if not row:
                return Response({"detail": "Працівника не знайдено"}, status=status.HTTP_404_NOT_FOUND)
            return Response(row[0], status=status.HTTP_200_OK)

    def put(self, request, id_employee):
        if request.user.empl_role != 'Менеджер':
            return Response({"detail": "Редагування доступне лише менеджерам"}, status=status.HTTP_403_FORBIDDEN)

        data = request.data
        with connection.cursor() as cursor:
            try:
                cursor.execute("""
                    UPDATE Employee SET 
                        empl_surname = %s, empl_name = %s, empl_patronymic = %s,
                        empl_role = %s, salary = %s, phone_number = %s,
                        city = %s, street = %s, zip_code = %s
                    WHERE id_employee = %s
                """, [
                    data.get('empl_surname'), data.get('empl_name'), data.get('empl_patronymic'),
                    data.get('empl_role'), data.get('salary'), data.get('phone_number'),
                    data.get('city'), data.get('street'), data.get('zip_code'), id_employee
                ])
                return Response({"message": "Дані працівника оновлено"}, status=status.HTTP_200_OK)
            except Exception as e:
                return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, id_employee):
        if request.user.empl_role != 'Менеджер':
            return Response({"detail": "Редагування доступне лише менеджерам"}, status=status.HTTP_403_FORBIDDEN)

        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM Employee WHERE id_employee = %s", [id_employee])

            return Response({"message": "Працівника успішно видалено"}, status=status.HTTP_204_NO_CONTENT)

#CRUD for categories
class CategoryListAPIView(APIView):
    permission_classes = [IsManager | IsCashier]

    def get(self, request):
        with connection.cursor() as cursor:
            cursor.execute("SELECT category_number, category_name FROM Category")
            categories = dictfetchall(cursor)
        return Response(categories, status=status.HTTP_200_OK)

    def post(self, request):
        if request.user.empl_role != "Менеджер":
            return Response({"detail": "Створення доступне лише менеджерам"}, status=status.HTTP_403_FORBIDDEN)

        data = request.data
        with connection.cursor() as cursor:
            try:
                cursor.execute("""
                    INSERT INTO Category (category_number, category_name) 
                    VALUES (%s, %s)
                """, [data.get('category_number'), data.get('category_name')])

                return Response({"message": "Категорію успішно створено"}, status=status.HTTP_201_CREATED)
            except Exception as e:
                return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

class CategoryDetailAPIView(APIView):
    permission_classes = [IsManager | IsCashier]

    def get(self, request, category_number):
        with connection.cursor() as cursor:
            cursor.execute("SELECT category_number, category_name FROM Category WHERE category_number = %s", [category_number])
            row = dictfetchall(cursor)

            if not row:
                return Response({"detail": "Категорію не знайдено"}, status=status.HTTP_404_NOT_FOUND)
            return Response(row[0], status=status.HTTP_200_OK)

    def put(self, request, category_number):
        if request.user.empl_role != 'Менеджер':
            return Response({"detail": "Редагування доступне лише менеджерам"}, status=status.HTTP_403_FORBIDDEN)

        data = request.data
        with connection.cursor() as cursor:
            try:
                cursor.execute("""
                    UPDATE Category 
                    SET category_name = %s 
                    WHERE category_number = %s
                """, [data.get('category_name'), category_number])

                return Response({"message": "Категорію оновлено"}, status=status.HTTP_200_OK)
            except Exception as e:
                return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, category_number):
        if request.user.empl_role != 'Менеджер':
            return Response({"detail": "Видалення доступне лише менеджерам"}, status=status.HTTP_403_FORBIDDEN)

        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM Category WHERE category_number = %s", [category_number])

            return Response({"message": "Категорію успішно видалено"}, status=status.HTTP_204_NO_CONTENT)

#CRUD for products
class ProductListAPIView(APIView):
    permission_classes = [IsManager | IsCashier]

    def get(self, request):
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT p.id_product, p.category_number, c.category_name, 
                       p.product_name, p.characteristics, p.manufacturer
                FROM Product p
                LEFT JOIN Category c ON p.category_number = c.category_number
            """)

            products = dictfetchall(cursor)
        return Response(products, status=status.HTTP_200_OK)

    def post(self, request):
        if request.user.empl_role != "Менеджер":
            return Response({"detail": "Створення доступне лише менеджерам"}, status=status.HTTP_403_FORBIDDEN)

        data = request.data
        with connection.cursor() as cursor:
            try:
                cursor.execute("""
                    INSERT INTO Product (id_product, category_number, product_name, characteristics, manufacturer)
                    VALUES (%s, %s, %s, %s, %s)
                """, [
                    data.get('id_product'), data.get('category_number'),
                    data.get('product_name'), data.get('characteristics'), data.get('manufacturer')
                ])

                return Response({"message": "Товар успішно створено"}, status=status.HTTP_201_CREATED)
            except Exception as e:
                return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

class ProductDetailAPIView(APIView):
    permission_classes = [IsManager | IsCashier]

    def get(self, request, id_product):
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT p.id_product, p.category_number, c.category_name, 
                       p.product_name, p.characteristics, p.manufacturer
                FROM Product p
                LEFT JOIN Category c ON p.category_number = c.category_number
                WHERE p.id_product = %s
            """, [id_product])
            row = dictfetchall(cursor)

        if not row:
            return Response({"detail": "Товар не знайдено"}, status=status.HTTP_404_NOT_FOUND)
        return Response(row[0], status=status.HTTP_200_OK)

    def put(self, request, id_product):
        if request.user.empl_role != 'Менеджер':
            return Response({"detail": "Редагування доступне лише менеджерам"}, status=status.HTTP_403_FORBIDDEN)

        data = request.data
        with connection.cursor() as cursor:
            try:
                cursor.execute("""
                    UPDATE Product 
                    SET category_number = %s, product_name = %s, characteristics = %s, manufacturer = %s 
                    WHERE id_product = %s
                """, [
                    data.get('category_number'), data.get('product_name'),
                    data.get('characteristics'), data.get('manufacturer'), id_product
                ])
                return Response({"message": "Товар оновлено"}, status=status.HTTP_200_OK)
            except IntegrityError:
                return Response({"error": "Вказаної категорії не існує"}, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, id_product):
        if request.user.empl_role != 'Менеджер':
            return Response({"detail": "Видалення доступне лише менеджерам"}, status=status.HTTP_403_FORBIDDEN)

        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM Product WHERE id_product = %s", [id_product])

        return Response({"message": "Товар успішно видалено"}, status=status.HTTP_204_NO_CONTENT)