import re
from decimal import Decimal, InvalidOperation
from datetime import datetime, date
from re import search

from django.contrib.auth.hashers import make_password
from django.db import connection, transaction, IntegrityError
from django.http import JsonResponse, Http404
from django.utils import timezone

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .permissions import IsManager, IsCashier

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

# Валідація назви категорії
def validate_category_name(name):
    if not name:
        return "Назва категорії є обов'язковою."

    if not re.match(r'^[A-Za-zА-Яа-яІіЇїЄєҐґ\s]+$', name):
        return "Назва категорії повинна містити лише літери та пробіли (без цифр і символів)."

    return None

#CRUD for categories
class CategoryListAPIView(APIView):
    permission_classes = [IsManager | IsCashier]

    def get(self, request):
        search = request.GET.get('search', '').strip()
        query = "SELECT category_number, category_name FROM Category WHERE 1=1"
        params = []

        if search:
            query += " AND LOWER(category_name) LIKE LOWER(%s)"
            params.append(f"{search}%")

        query += " ORDER BY category_name ASC"

        with connection.cursor() as cursor:
            cursor.execute(query, params)
            categories = dictfetchall(cursor)
        return Response(categories, status=status.HTTP_200_OK)

    def post(self, request):
        if request.user.empl_role != "Менеджер":
            return Response({"detail": "Створення доступне лише менеджерам"}, status=status.HTTP_403_FORBIDDEN)

        data = request.data
        category_name = data.get('category_name', '').strip()

        name_error = validate_category_name(category_name)
        if name_error:
            return Response({"error": name_error}, status=status.HTTP_400_BAD_REQUEST)

        with connection.cursor() as cursor:
            try:
                cursor.execute("SELECT MAX(category_number) FROM Category")
                max_id = cursor.fetchone()[0]
                next_id = (max_id or 0) + 1

                cursor.execute("""
                               INSERT INTO Category (category_number, category_name)
                               VALUES (%s, %s)
                               """, [next_id, data.get('category_name')])

                return Response({"message": "Категорію успішно створено"}, status=status.HTTP_201_CREATED)
            except Exception as e:
                if "UNIQUE" in str(e) or "primary key" in str(e).lower():
                    return Response({"error": "Категорія з таким номером вже існує"},
                                    status=status.HTTP_400_BAD_REQUEST)
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
        category_name = data.get('category_name', '').strip()

        name_error = validate_category_name(category_name)
        if name_error:
            return Response({"error": name_error}, status=status.HTTP_400_BAD_REQUEST)

        with connection.cursor() as cursor:
            try:
                cursor.execute("""
                    UPDATE Category 
                    SET category_name = %s 
                    WHERE category_number = %s
                """, [data.get('category_name'), category_number])

                if cursor.rowcount == 0:
                    return Response({"detail": "Категорію не знайдено."}, status=status.HTTP_404_NOT_FOUND)

                return Response({"message": "Категорію оновлено"}, status=status.HTTP_200_OK)
            except Exception as e:
                return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, category_number):
        if request.user.empl_role != 'Менеджер':
            return Response({"detail": "Видалення доступне лише менеджерам"}, status=status.HTTP_403_FORBIDDEN)

        with connection.cursor() as cursor:
            try:
                cursor.execute("DELETE FROM Category WHERE category_number = %s", [category_number])

                if cursor.rowcount == 0:
                    return Response({"detail": "Категорію не знайдено для видалення."},
                                    status=status.HTTP_404_NOT_FOUND)

                return Response({"message": "Категорію успішно видалено"}, status=status.HTTP_204_NO_CONTENT)
            except IntegrityError:
                return Response({"error": "Неможливо видалити категорію, оскільки до неї прив'язані товари!"},
                                status=status.HTTP_400_BAD_REQUEST)
            except Exception as e:
                return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

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
    permission_classes = [IsAuthenticated]
    def get(self, request):
        search = request.query_params.get('search', '')
        percent = request.query_params.get('percent')
        sort = request.query_params.get('sort')

        with connection.cursor() as cursor:
            try:
                sql = ("SELECT id_card, cust_name, percent "
                       "FROM CustomerCard "
                       "WHERE 1=1")
                params = []
                if search:
                    sql += " AND cust_name LIKE %s"
                    params.append(f"%{search}%")

                # Тут логіка серіалізації замінюється на повернення JSON
                return Response(dictfetchall(cursor), status=status.HTTP_200_OK)
            except Exception as e:
                return Response({"error": f"Помилка при отриманні карток клієнтів: {str(e)}"},
                                status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def post(self, request):
        permission_classes = [IsManager]
        data = request.data
        try:
            with connection.cursor() as cursor:
                cursor.execute(""" INSERT INTO CustomerCard (card_number, cust_surname, cust_name, cust_patronymic,
                  phone_number, city, street, zip_code, percent)
                               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                               [data.get('id_card'), data.get('cust_surname'), data.get('cust_name'), data.get('cust_patronymic'), data.get('phone_number'), data.get('city'),
                                data.get('street'), data.get('zip_code'), data.get('percent')])

                return Response({"message": "Карта клієнта успішно створена"}, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response({"error": f"Помилка при створенні картки клієнта: {str(e)}"},
                            status=status.HTTP_400_BAD_REQUEST)

class CustomerCardDetailAPIView(APIView):
    def get_object(self, pk):
        with connection.cursor() as cursor:
            try:
                cursor.execute("SELECT * FROM CustomerCard "
                               "WHERE id_card = %s", [pk])
                row = cursor.fetchone()
                if not row:
                    return None # Не знайдено
                # Повертаємо кортеж/рядок, який потім клієнт трансформує в JSON
                return dictfetchall(cursor)[0]
            except Exception as e:
                 raise Http404()

    def get(self, request, pk):
        card_data = self.get_object_sql(pk)
        if card_data is None:
            return Response({"detail": "Карту клієнта не знайдено"}, status=status.HTTP_404_NOT_FOUND)
        return Response(card_data, status=status.HTTP_200_OK)

    def put(self, request, pk):
        data = request.data
        with connection.cursor() as cursor:
            try:
                cursor.execute("""
                               UPDATE CustomerCard
                               SET cust_surname = %s,
                                   cust_name = %s,
                                   cust_patronymic = %s,
                                   phone_number = %s,
                                   city = %s,
                                   street = %s,
                                   zip_code = %s,
                                   percent = %s
                                   WHERE id_card = %s
                               """, [data.get('cust_surname'), data.get('cust_name'), data.get('cust_patronymic'), data.get('phone_number'),
                                     data.get('city'), data.get('street'), data.get('zip_code'), data.get('percent'), pk])

                if cursor.rowcount == 0:
                    return Response({"detail": "Карта не знайдена для оновлення."}, status=status.HTTP_404_NOT_FOUND)

                return Response({"message": "Карта успішно оновлена"}, status=status.HTTP_200_OK)
            except Exception as e:
                return Response({"error": f"Помилка при оновленні картки клієнта: {str(e)}"},
                                status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, pk):
        with connection.cursor() as cursor:
            try:
                cursor.execute("DELETE FROM CustomerCard "
                               "WHERE id_card = %s", [pk])
                if cursor.rowcount == 0:
                    return Response({"detail": "Карта не знайдена для видалення."}, status=status.HTTP_404_NOT_FOUND)

                return Response(status=status.HTTP_204_NO_CONTENT)
            except Exception as e:
                return Response({"error": f"Помилка при видаленні картки клієнта: {str(e)}"},
                                status=status.HTTP_500_INTERNAL_SERVER_ERROR)


#CRUD for checks
class CheckListAPIView(APIView):
    permission_classes = [IsAuthenticated]
    def get(self, request):
        cashier_id = request.query_params.get('cashier_id')
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')

        with connection.cursor() as cursor:
            try:
                sql = "SELECT * FROM StoreCheck WHERE 1=1"
                params = []
                if cashier_id:
                    sql += " AND id_employee = %s"
                    params.append(cashier_id)

                if start_date and end_date:
                    sql += " AND print_date BETWEEN %s AND %s"
                    params.extend([start_date, end_date])

                cursor.execute(sql, params)
                return Response(dictfetchall(cursor), status=status.HTTP_200_OK)
            except Exception as e:
                return Response({"error": f"Помилка при отриманні списку чеків: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


def post(self, request):
        if request.user.empl_role != "Касир":
            return Response({"detail": "Створення чеків доступне лише касирам"}, status=status.HTTP_403_FORBIDDEN)

        check_data = request.data
        items_list = check_data.pop('items')
        with connection.cursor() as cursor:
            try:
                check_number = check_data.get('check_number')
                id_employee = check_data.get('id_employee')
                card_number = check_data.get('card_number')
                current_time = timezone.now()
                subtotal = 0
                for item in items_list:
                    cursor.execute("SELECT selling_price "
                                   "FROM StoreProduct "
                                   "WHERE upc = %s", [item['upc']])
                    row = cursor.fetchone()
                    if not row:
                        return Response({"error": f"Товар з UPC {item['upc']} не знайдено"},
                                        status=status.HTTP_400_BAD_REQUEST)
                    price = row[0]
                    subtotal += price * item['quantity']

                vat_amount = subtotal * Decimal('0.2')
                final_sum = subtotal + vat_amount
                cursor.execute("""
                               INSERT INTO StoreCheck (check_number, id_employee, card_number, print_date, sum_total, vat)
                               VALUES (%s, %s, %s, %s, %s, %s)
                               """, [check_number, id_employee, card_number, current_time, final_sum, vat_amount])

                for item in items_list:
                    cursor.execute("""
                                   INSERT INTO Sale (upc, check_number, product_number, selling_price)
                                   VALUES (%s, %s, %s, %s)
                                   """, [item['upc'], check_number, item.get('product_number'), item['selling_price']])

                return Response({"message": "Чек успішно створено"}, status=status.HTTP_201_CREATED)
            except Exception as e:
                return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)


class CheckDetailAPIView(APIView):
    def get(self, request, pk):
        with connection.cursor() as cursor:
            try:
                cursor.execute("SELECT * FROM StoreCheck "
                               "WHERE check_number = %s", [pk])
                card_data = dictfetchall(cursor)

                if not card_data:
                    return Response({"detail": "Чек не знайдено"}, status=status.HTTP_404_NOT_FOUND)
                return Response(card_data[0], status=status.HTTP_200_OK)
            except Exception as e:
                return Response({"error": f"Помилка при отриманні чека: {str(e)}"},
                                status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def put(self, request, pk):
        if request.user.empl_role != "Менеджер":
            return Response({"detail": "Оновлення чеків доступне лише менеджерам"}, status=status.HTTP_403_FORBIDDEN)
        with connection.cursor() as cursor:
            try:
                cursor.execute("UPDATE StoreCheck SET ... WHERE check_number = %s", [pk])
                if cursor.rowcount == 0:
                    return Response({"detail": "Чек не знайдено для оновлення."}, status=status.HTTP_404_NOT_FOUND)

                return Response({"message": "Чек успішно оновлено"}, status=status.HTTP_200_OK)
            except Exception as e:
                return Response({"error": f"Помилка при оновленні чека: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, pk):
        if request.user.empl_role != 'Менеджер':
            return Response({"detail": "Видалення чеків доступне лише менеджерам"}, status=status.HTTP_403_FORBIDDEN)

        with connection.cursor() as cursor:
            try:
                cursor.execute("DELETE FROM Check WHERE check_number = %s", [pk])
                return Response({"message": "Чек успішно видалено"}, status=status.HTTP_204_NO_CONTENT)
            except Exception as e:
                return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

#CRUD for store products
class StoreProductListAPIView(APIView):
    permission_classes = [IsAuthenticated]
    def get(self, request):
        with connection.cursor() as cursor:
            try:
                sql = """
                      SELECT p.id_product,
                             p.category_number,
                             c.category_name,
                             p.product_name,
                             p.characteristics,
                             p.manufacturer
                      FROM Product p
                               LEFT JOIN Category c ON p.category_number = c.category_number
                      """
                cursor.execute(sql)
                return Response(dictfetchall(cursor), status=status.HTTP_200_OK)
            except Exception as e:
                return Response({"error": f"Помилка при отриманні товарів: {str(e)}"},
                                status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def post(self, request):
        if request.user.empl_role != "Менеджер":
            return Response({"detail": "Створення доступне лише менеджерам"}, status=status.HTTP_403_FORBIDDEN)

        data = request.data
        with connection.cursor() as cursor:
            try:
                cursor.execute("""
                               INSERT INTO Product (id_product, category_number, product_name, characteristics,
                                                    manufacturer)
                               VALUES (%s, %s, %s, %s, %s) """, [
                                   data.get('id_product'), data.get('category_number'),
                                   data.get('product_name'), data.get('characteristics'), data.get('manufacturer')
                               ])
                return Response({"message": "Товар успішно створено"}, status=status.HTTP_201_CREATED)
            except Exception as e:
                return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)


class StoreProductDetailsAPIView(APIView):
    def get(self, request, pk):
        with connection.cursor() as cursor:
            try:
                # Отримання деталей через SQL
                cursor.execute("""
                               SELECT p.id_product,
                                      p.category_number,
                                      c.category_name,
                                      p.product_name,
                                      p.characteristics,
                                      p.manufacturer
                               FROM Product p
                                        LEFT JOIN Category c ON p.category_number = c.category_number
                               WHERE p.id_product = %s  """, [pk])
                row = dictfetchall(cursor)

                if not row:
                    return Response({"detail": "Товар не знайдено"}, status=status.HTTP_404_NOT_FOUND)
                return Response(row[0], status=status.HTTP_200_OK)
            except Exception as e:
                return Response({"error": f"Помилка при отриманні деталей товару: {str(e)}"},
                                status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def put(self, request, pk):
        if request.user.empl_role != 'Менеджер':
            return Response({"detail": "Редагування доступне лише менеджерам"}, status=status.HTTP_403_FORBIDDEN)
        data = request.data
        with connection.cursor() as cursor:
            try:
                cursor.execute("""
                               UPDATE Product
                               SET category_number = %s,
                                   product_name    = %s,
                                   characteristics = %s,
                                   manufacturer    = %s
                               WHERE id_product = %s
                               """, [data.get('category_number'), data.get('product_name'), data.get('characteristics'),
                                     data.get('manufacturer'), pk])

                if cursor.rowcount == 0:
                    return Response({"detail": "Товар не знайдена для редагування."}, status=status.HTTP_404_NOT_FOUND)

                return Response({"message": "Товар оновлено"}, status=status.HTTP_200_OK)
            except IntegrityError:
                return Response({"error": "Вказаної категорії не існує."}, status=status.HTTP_400_BAD_REQUEST)
            except Exception as e:
                return Response({"error": f"Помилка при оновленні товару: {str(e)}"},
                                status=status.HTTP_500_INTERNAL_SERVER_ERROR)


    def delete(self, request, pk):
        if request.user.empl_role != 'Менеджер':
            return Response({"detail": "Видалення доступне лише менеджерам"}, status=status.HTTP_403_FORBIDDEN)

        with connection.cursor() as cursor:
            try:
                cursor.execute("DELETE FROM Product"
                               " WHERE id_product = %s", [pk])
                if cursor.rowcount == 0:
                    return Response({"detail": "Товар не знайдена для видалення."}, status=status.HTTP_404_NOT_FOUND)
                return Response({"message": "Товар успішно видалено"}, status=status.HTTP_204_NO_CONTENT)
            except Exception as e:
                return Response({"error": f"Помилка при видаленні товару: {str(e)}"},
                                status=status.HTTP_500_INTERNAL_SERVER_ERROR)
