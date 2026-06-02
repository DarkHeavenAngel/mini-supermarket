import json
import re
from ast import Store
from decimal import Decimal, InvalidOperation
from datetime import datetime, date
from re import search

import current_time
import cursor
from django.contrib.auth.hashers import make_password
from django.db import connection, transaction, IntegrityError
from django.http import JsonResponse, Http404
from django.utils import timezone

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .permissions import IsManager, IsCashier

#Functiobn to show profile
class EmployeeProfileAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        my_id = request.user.id_employee

        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT id_employee, empl_surname, empl_name, empl_patronymic, 
                       empl_role, salary, date_of_birth, date_of_start, 
                       phone_number, city, street, zip_code 
                FROM Employee WHERE id_employee = %s
            """, [my_id])
            row = dictfetchall(cursor)

        if not row:
            return Response({"detail": "Профіль не знайдено"}, status=status.HTTP_404_NOT_FOUND)

        return Response(row[0], status=status.HTTP_200_OK)

#Допоміжна функція для перетворення результатів SQL-запиту в список словників (JSON)
def dictfetchall(cursor):
    columns = [col[0] for col in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]

# перероблена глобальна валідація робітників для sql запитів
def validate_employee_data(data, check_id=False):
    id_employee = data.get('id_employee')
    phone_number = data.get('phone_number')
    date_of_birth = data.get('date_of_birth')
    salary = data.get('salary')

    # валідація ID при стоверні
    if check_id and not id_employee:
        return "Індентифікаційний номер сповробітника є обов'язковим"

    # валідація телефону (не більше 13 символів + формат +380)
    if not phone_number or not re.match(r'^\+380\d{9}$', str(phone_number)):
        return "Номер телефону повинен починатися з '+380' та містити всього 13 символів"

    # валідація зарплати (не може бути від'ємною)
    if salary is not None:
        try:
            if Decimal(str(salary)) < 0:
                return "Заробітня плата не може бути від'ємною"
        except (ValueError, TypeError, InvalidOperation):
            return "Некоректне значення заробітньої плати"

    # валідація віку (не менше 18)
    if not date_of_birth:
        return "Дата народження є обов'язковою"
    try:
        if isinstance(date_of_birth, str):
            born_date = datetime.strptime(date_of_birth, "%Y-%m-%d").date()
        else:
            born_date = date_of_birth
    except (ValueError, TypeError):
        return "Некоректний формат дати народження. Використовуйте РРРР-ММ-ДД"

    today = date.today()
    age = today.year - born_date.year - ((today.month, today.day) < (born_date.month, born_date.day))

    if age < 18:
        return "Вік працівника не може бути меншим за 18 років"

    return None

# глобальна валідація для товару в магазині
def validate_store_product_data(data):
    # валідація на невід'ємну ціну та кількість
    try:
        price = Decimal(str(data.get('selling_price', '0')))
        if price < 0:
            return "Ціна продажу не може бути від'ємною"
    except (ValueError, TypeError):
        return "Некоректне значення кількості одиниць"

    return None

# глобальна валідація чеку
def validate_check_data(item_list):
    # кількість товару > 0
    if not item_list or not isinstance(item_list, list) or len(item_list) == 0:
        return "Чек повинен містити хоча б один товар"

    for item in item_list:
        try:
            qty = int(item.get('qty', 0))
            if qty < 0:
                return f"Кількість купленого товару (UPC: {item.get('upc')}) повина бути більшою за 0"
        except (ValueError, TypeError):
            return "Некоректне значення кількості товару в чеку"

        return None

#CRUD for employees
class EmployeeListAPIView(APIView):
    permission_classes = [IsManager]

    def get(self, request):
        search = request.GET.get('search', '').strip()
        role = request.GET.get('role', '').strip()

        query = """
            SELECT id_employee, empl_surname, empl_name, empl_patronymic,
                   empl_role, salary, date_of_birth, date_of_start,
                   phone_number, city, street, zip_code
            FROM Employee
            WHERE 1 = 1
        """
        params = []

        if search:
            query += " AND LOWER(empl_surname) LIKE LOWER(%s)"
            params.append(f"{search}%")

        if role:
            query += " AND empl_role = %s"
            params.append(role)

        query += " ORDER BY empl_surname ASC"

        with connection.cursor() as cursor:
            cursor.execute(query, params)
            employees = dictfetchall(cursor)

        return Response(employees, status=status.HTTP_200_OK)

    def post(self, request):
        data = request.data

        # виклик валідації працівника
        validation_error = validate_employee_data(data, check_id=True)
        if validation_error:
            return Response({"error": validation_error}, status=status.HTTP_400_BAD_REQUEST)

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
                # перехоплення дубльованого ключа
                if "UNIQUE" in str(e) or "primary key" in str(e).lower():
                    return Response({"error": "Працівник з таким ID вже існує в системі"}, status=status.HTTP_400_BAD_REQUEST)
                return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

class EmployeeDetailAPIView(APIView):
    permission_classes = [IsManager | IsCashier]

    def get(self, request, id_employee):
        if request.user.empl_role != 'Менеджер' and request.user.id_employee != id_employee:
            return Response({"detail": "Ви не маєте доступу до даних інших працівників"}, status=status.HTTP_403_FORBIDDEN)

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

        # виклик валідації працівника
        validation_error = validate_employee_data(data, check_id=True)
        if validation_error:
            return Response({"error": validation_error}, status=status.HTTP_400_BAD_REQUEST)

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

                if cursor.rowcount == 0:
                    return Response({"detail": "Працівника не знайдено"}, status=status.HTTP_404_NOT_FOUND)

                return Response({"message": "Дані працівника оновлено"}, status=status.HTTP_200_OK)
            except Exception as e:
                return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, id_employee):
        if request.user.empl_role != 'Менеджер':
            return Response({"detail": "Видалення доступне лише менеджерам"}, status=status.HTTP_403_FORBIDDEN)

        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM Employee WHERE id_employee = %s", [id_employee])
            if cursor.rowcount == 0:
                return Response({"detail": "Працівника не знайдено"}, status=status.HTTP_404_NOT_FOUND)
            return Response({"message": "Працівника успішно видалено"}, status=status.HTTP_204_NO_CONTENT)

#CRUD for categories
class CategoryListAPIView(APIView):
    permission_classes = [IsManager | IsCashier]

    def get(self, request):
        with connection.cursor() as cursor:
            cursor.execute("SELECT category_number, category_name FROM Category ORDER BY category_name ASC") # + фільтрація за назвою
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
                ORDER BY p.product_name ASC 
            """) # + фільтрація за ім'ям

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

# Інформація для звіту на головній сторінці
class DashboardStatsAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        with connection.cursor() as cursor:
            # Чеки
            cursor.execute("SELECT COUNT(*) FROM StoreCheck WHERE DATE(print_date) = CURRENT_DATE;")
            checks_today = cursor.fetchone()[0]

            # Акційні товари
            cursor.execute("SELECT COUNT(*) FROM StoreProduct WHERE promotional_product = TRUE;")
            promo_items = cursor.fetchone()[0]

            # Кількість клієнтських карткок
            cursor.execute("SELECT COUNT(*) FROM CustomerCard;")
            total_cards = cursor.fetchone()[0]

        return Response({
            "checks_today": checks_today,
            "promo_items": promo_items,
            "total_cards": total_cards
        }, status=status.HTTP_200_OK)

#CRUD for Customer Cards
class CustomerCardListAPIView(APIView):
    permission_classes = [IsManager | IsCashier]

    def get(self, request):
        search = request.query_params.get('search', '')
        with connection.cursor() as cursor:
            sql = "SELECT * FROM CustomerCard WHERE 1=1"
            params = []
            if search:
                # Пошук за прізвищем або ім'ям
                sql += " AND (cust_surname ILIKE %s OR cust_name ILIKE %s)"
                params.extend([f"%{search}%", f"%{search}%"])

            cursor.execute(sql, params)
            return Response(dictfetchall(cursor), status=status.HTTP_200_OK)

    def post(self, request):
        data = request.data
        with connection.cursor() as cursor:
            try:
                cursor.execute("""
                    INSERT INTO CustomerCard (card_number, cust_surname, cust_name, cust_patronymic, phone_number, city, street, zip_code, percent)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, [
                            data.get('card_number'), data.get('cust_surname'), data.get('cust_name'),data.get('cust_patronymic'),
                            data.get('phone_number'), data.get('city'), data.get('street'), data.get('zip_code'), data.get('percent')
                ])
                return Response({"message": "Карту клієнта створено"}, status=status.HTTP_201_CREATED)
            except IntegrityError:
                return Response({"error": "Картка з таким номером вже існує"}, status=status.HTTP_400_BAD_REQUEST)
            except Exception as e:
                return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

class CustomerCardDetailAPIView(APIView):
    permission_classes = [IsManager | IsCashier]

    def get(self, request, card_number):
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM CustomerCard WHERE card_number = %s", [card_number])
            row = dictfetchall(cursor)
        if not row:
            return Response({"detail": "Карту не знайдено"}, status=status.HTTP_404_NOT_FOUND)
        return Response(row[0], status=status.HTTP_200_OK)

    def put(self, request, card_number):
        if request.user.empl_role != 'Менеджер':
            return Response({"detail": "Редагування доступне лише менеджерам"}, status=status.HTTP_403_FORBIDDEN)

        data = request.data
        with connection.cursor() as cursor:
            try:
                cursor.execute("""
                    UPDATE CustomerCard
                    SET cust_surname = %s, cust_name = %s, cust_patronymic = %s,
                        phone_number = %s, city = %s, street = %s, zip_code = %s, percent = %s
                    WHERE card_number = %s
                """, [
                        data.get('cust_surname'), data.get('cust_name'), data.get('cust_patronymic'),
                        data.get('phone_number'), data.get('city'), data.get('street'),
                        data.get('zip_code'), data.get('percent'), card_number
                    ])
                return Response({"message": "Карту успішно оновлено"}, status=status.HTTP_200_OK)
            except Exception as e:
                return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, card_number):
        if request.user.empl_role != 'Менеджер':
            return Response({"detail": "Видалення доступне лише менеджерам."}, status=status.HTTP_403_FORBIDDEN)

        with connection.cursor() as cursor:
            try:
                cursor.execute("DELETE FROM CustomerCard WHERE card_number = %s", [card_number])
                return Response({"message": "Карту видалено."}, status=status.HTTP_200_OK)
            except IntegrityError:
                return Response({"error": "Неможливо видалити карту, оскільки за нею вже є пробиті чеки"}, status=status.HTTP_400_BAD_REQUEST)

#CRUD for checks
class CheckListAPIView(APIView):
    permission_classes = [IsManager | IsCashier]

    def get(self, request):
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT  c.check_number, c.print_date, c.sum_total, c.vat,
                        e.empl_surname, e.empl_name, card.percent
                FROM StoreCheck c
                JOIN Employee e ON c.id_employee = e.id_employee
                LEFT JOIN CustomerCard card ON c.card_number = card.card_number
                ORDER BY c.print_date DESC
            """)
            return Response(dictfetchall(cursor), status=status.HTTP_200_OK)

    @transaction.atomic
    def post(self, request):
        if request.user.empl_role != 'Касир':
            return Response({"detail": "Пробивати чеки можуть лише касири"}, status=status.HTTP_403_FORBIDDEN)

        data = request.data
        items_list = data.get('items', [])

        with connection.cursor() as cursor:
            try:
                check_number = data.get('check_number')
                id_employee = request.user.id_employee
                card_number = data.get('card_number')

                subtotal = Decimal('0.0')
                for item in items_list:
                    cursor.execute("SELECT selling_price FROM StoreProduct WHERE upc = %s", [item['upc']])
                    price_row = cursor.fetchone()
                    if not price_row:
                        raise Exception(f"Товар з UPC {item['upc']} не знайдено в магазині")

                    price = Decimal(str(price_row[0]))
                    subtotal += price * Decimal(str(item['quantity']))

                discount_percent = Decimal('0.0')
                if card_number:
                    cursor.execute("SELECT percent FROM CustomerCard WHERE card_number = %s", [card_number])
                    card_row = cursor.fetchone()
                    if card_row:
                        discount_percent = Decimal(str(card_row[0]))

                multiplier = (Decimal('100') - discount_percent) / Decimal('100')
                final_sum = subtotal * multiplier

                vat_amount = final_sum * Decimal('0.2')

                cursor.execute("""
                    INSERT INTO StoreCheck (check_number, id_employee, card_number, print_date, sum_total, vat)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, [check_number, id_employee, card_number, timezone.now(), final_sum, vat_amount])

                for item in items_list:
                    cursor.execute("SELECT selling_price FROM StoreProduct WHERE upc = %s", [item['upc']])
                    selling_price = Decimal(str(cursor.fetchone()[0]))

                    cursor.execute("""
                        INSERT INTO Sale (upc, check_number, product_number, selling_price)
                        VALUES (%s, %s, %s, %s)
                    """, [item['upc'], check_number, item['quantity'], selling_price])

                    cursor.execute("""
                        UPDATE StoreProduct
                        SET products_number = products_number - %s
                        WHERE upc = %s
                    """, [item['quantity'], item['upc']])

                return Response({"message": "Чек успішно створено!"}, status=status.HTTP_201_CREATED)
            except Exception as e:
                return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

class CheckDetailAPIView(APIView):
    permission_classes = [IsManager | IsCashier]

    def get(self, request, check_number):
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM StoreCheck WHERE check_number = %s", [check_number])
            check_data = dictfetchall(cursor)

            if not check_data:
                return Response({"detail": "Чек не знайдено"}, status=status.HTTP_404_NOT_FOUND)

            cursor.execute("""
                SELECT s.upc, p.product_name, s.product_number, s.selling_price
                FROM Sale s
                JOIN StoreProduct sp ON s.upc = sp.upc
                JOIN Product p ON sp.id_product = p.id_product
                WHERE s.check_number = %s
            """, [check_number])
            sales_data = dictfetchall(cursor)

            result = check_data[0]
            result['items'] = sales_data

        return Response(result, status=status.HTTP_200_OK)

    def delete(self, request, check_number):
        if request.user.empl_role != 'Менеджер':
            return Response({"detail": "Видаляти чеки можуть лише менеджери."}, status=status.HTTP_403_FORBIDDEN)

        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM StoreCheck WHERE check_number = %s", [check_number])
        return Response({"message": "Чек успішно видалено."}, status=status.HTTP_200_OK)

#CRUD for store products
class StoreProductListAPIView(APIView):
    permission_classes = [IsManager | IsCashier]

    def get(self, request):
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT sp.upc, sp.upc_prom, p.product_name, sp.selling_price,
                       sp.products_number, sp.promotional_product
                FROM StoreProduct sp
                JOIN Product p ON sp.id_product = p.id_product
            """)
            return Response(dictfetchall(cursor), status=status.HTTP_200_OK)

    def post(self, request):
        if request.user.empl_role != 'Менеджер':
            return Response({"detail": "Додавати товари в магазин можуть лише менеджери"}, status=status.HTTP_403_FORBIDDEN)

        data = request.data
        id_product = data.get('id_product')
        promotional_product = data.get('promotional_product', False)
        upc_prom = data.get('upc_prom')
        selling_price = data.get('selling_price', 0)

        with connection.cursor() as cursor:
            try:
                # ЗАМІНА МЕТОДУ clean()
                cursor.execute("SELECT promotional_product FROM StoreProduct WHERE id_product = %s", [id_product])
                existing_records = cursor.fetchall()

                if len(existing_records) >= 2:
                    return Response(
                        {
                            "error": "Для цього товару вже існує максимально можлива кількість записів (звичайний та акційний)"}, status=status.HTTP_400_BAD_REQUEST)

                for row in existing_records:
                    if row[0] == promotional_product:
                        status_str = "акційний" if promotional_product else "звичайний"
                        return Response(
                            {"error": f"Для цього товару вже існує {status_str} варіант. Оберіть інший статус"}, status=status.HTTP_400_BAD_REQUEST)

                # ЗАМІНА МЕТОДУ save(): Автоматична знижка 20%
                if promotional_product and upc_prom:
                    cursor.execute("SELECT selling_price FROM StoreProduct WHERE upc = %s", [upc_prom])
                    base_price_row = cursor.fetchone()
                    if base_price_row:
                        base_price = float(base_price_row[0])
                        selling_price = base_price * 0.8

                cursor.execute("""
                    INSERT INTO StoreProduct (upc, upc_prom, id_product, selling_price, products_number, promotional_product)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, [
                            data.get('upc'), upc_prom, id_product, selling_price, data.get('products_number'), promotional_product])

                return Response({"message": "Товар успішно додано на полиці магазину"}, status=status.HTTP_201_CREATED)

            except IntegrityError:
                return Response({"error": "Такий UPC вже існує або вказано неіснуючий id_product"},
                                status=status.HTTP_400_BAD_REQUEST)
            except Exception as e:
                return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)


class StoreProductDetailAPIView(APIView):
    permission_classes = [IsManager | IsCashier]

    def get(self, request, upc):
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT sp.upc, sp.upc_prom, p.id_product, p.product_name, p.characteristics, p.manufacturer,
                       sp.selling_price, sp.products_number, sp.promotional_product
                FROM StoreProduct sp
                JOIN Product p ON sp.id_product = p.id_product
                WHERE sp.upc = %s
            """, [upc])
            row = dictfetchall(cursor)

        if not row:
            return Response({"detail": "Товар з таким UPC не знайдено"}, status=status.HTTP_404_NOT_FOUND)

        return Response(row[0], status=status.HTTP_200_OK)

    def put(self, request, upc):
        if request.user.empl_role != 'Менеджер':
            return Response({"detail": "Редагування доступне лише менеджерам"}, status=status.HTTP_403_FORBIDDEN)

        data = request.data

        validation_error = validate_store_product_data(data)
        if validation_error:
            return Response({"error": validation_error}, status=status.HTTP_400_BAD_REQUEST)

        with connection.cursor() as cursor:
            try:
                cursor.execute("""
                    UPDATE StoreProduct
                    SET selling_price = %s, products_number = %s, promotional_product = %s
                    WHERE upc = %s
                """, [
                            data.get('selling_price'),
                            data.get('products_number'),
                            data.get('promotional_product', False),
                            upc])

                if cursor.rowcount == 0:
                    return Response({"detail": "Товар не знайдено для оновлення"}, status=status.HTTP_404_NOT_FOUND)

                return Response({"message": "Дані про товар у магазині оновлено"}, status=status.HTTP_200_OK)
            except Exception as e:
                return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, upc):
        if request.user.empl_role != 'Менеджер':
            return Response({"detail": "Видалення доступне лише менеджерам"}, status=status.HTTP_403_FORBIDDEN)

        with connection.cursor() as cursor:
            try:
                cursor.execute("DELETE FROM StoreProduct WHERE upc = %s", [upc])

                if cursor.rowcount == 0:
                    return Response({"detail": "Товар не знайдено"}, status=status.HTTP_404_NOT_FOUND)

                return Response({"message": "Товар успішно списано з магазину"}, status=status.HTTP_204_NO_CONTENT)
            except IntegrityError:
                return Response({
                    "error": "Неможливо видалити товар, оскільки він фігурує у створених чеках (таблиця Sale)"}, status=status.HTTP_400_BAD_REQUEST)
