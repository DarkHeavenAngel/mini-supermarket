import re
from decimal import Decimal, InvalidOperation
from datetime import datetime, date

from django.contrib.auth.hashers import make_password
from django.db import connection, transaction, IntegrityError
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
def validate_employee_data(data, check_id=False, check_password=False):
    id_employee = data.get('id_employee')
    phone_number = data.get('phone_number')
    date_of_birth = data.get('date_of_birth')
    date_of_start = data.get('date_of_start')
    salary = data.get('salary')
    password = data.get('password')

    # валідація ID при стоверні
    if check_id and not id_employee:
        return "Індентифікаційний номер сповробітника є обов'язковим"

    # Валідація пароля (лише при створенні)
    if check_password:
        if not password or len(password) < 8:
            return "Пароль повинен містити не менше 8 символів"
        # Перевірка на наявність хоча б однієї літери та однієї цифри
        if not re.search(r'[A-Za-z]', password) or not re.search(r'\d', password):
            return "Пароль повинен містити хоча б одну літеру та одну цифру"

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

    # Валідація віку НА МОМЕНТ ПОЧАТКУ РОБОТИ
    if not date_of_birth:
        return "Дата народження є обов'язковою"
    if not date_of_start:
        return "Дата початку роботи є обов'язковою"

    try:
        if isinstance(date_of_birth, str):
            born_date = datetime.strptime(date_of_birth, "%Y-%m-%d").date()
        else:
            born_date = date_of_birth

        if isinstance(date_of_start, str):
            start_date = datetime.strptime(date_of_start, "%Y-%m-%d").date()
        else:
            start_date = date_of_start
    except (ValueError, TypeError):
        return "Некоректний формат дат. Використовуйте РРРР-ММ-ДД"

    age_at_start = start_date.year - born_date.year - ((start_date.month, start_date.day) < (born_date.month, born_date.day))

    if age_at_start < 18:
        return "На момент початку роботи працівнику має виповнитися 18 років, перевірте дату народження!"

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
        validation_error = validate_employee_data(data, check_id=True, check_password=True)
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
        validation_error = validate_employee_data(data, check_id=True, check_password=False)
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
            try:
                cursor.execute("DELETE FROM Employee WHERE id_employee = %s", [id_employee])

                if cursor.rowcount == 0:
                    return Response({"detail": "Працівника не знайдено"}, status=status.HTTP_404_NOT_FOUND)

                return Response({"message": "Працівника успішно видалено"}, status=status.HTTP_204_NO_CONTENT)
            except IntegrityError:
                return Response({"error": "Неможливо видалити працівника, оскільки за ним закріплені чеки!"},
                                status=status.HTTP_400_BAD_REQUEST)

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
        search = request.GET.get('search', '').strip()
        category = request.GET.get('category', '').strip()

        query = """
            SELECT p.id_product, p.category_number, c.category_name,
                   p.product_name, p.characteristics, p.manufacturer
            FROM Product p
            LEFT JOIN Category c ON p.category_number = c.category_number
            WHERE 1 = 1
        """
        params = []

        # Пошук за назвою товару
        if search:
            query += " AND LOWER(p.product_name) LIKE LOWER(%s)"
            params.append(f"{search}%")

        # Фільтрація за категорією
        if category:
            query += " AND p.category_number = %s"
            params.append(category)

        query += " ORDER BY p.product_name ASC"

        with connection.cursor() as cursor:
            try:
                cursor.execute(query, params)
                products = dictfetchall(cursor)

                return Response(products, status=status.HTTP_200_OK)

            except Exception as e:
                return Response({"error": f"Помилка при завантаженні товарів: {str(e)}"},
                                status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def post(self, request):
        if request.user.empl_role != "Менеджер":
            return Response({"detail": "Додавати товари можуть лише менеджери"}, status=status.HTTP_403_FORBIDDEN)

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
            try:
                cursor.execute("DELETE FROM Product WHERE id_product = %s", [id_product])
                return Response(status=status.HTTP_204_NO_CONTENT)
            except IntegrityError:
                return Response({"error": "Неможливо видалити товар, він є в чеках"}, status=400)

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

# Валідація клієнтів
def validate_customer_data(data):
    # Валідація телефону
    phone = str(data.get('phone_number', ''))
    if not re.match(r'^\+380\d{9}$', phone):
        return "Номер телефону повинен починатися з '+380' та мати 13 символів"

    try:
        percent = Decimal(str(data.get('percent', 0)))
        if percent < 0 or percent > 100:
            return "Відсоток знижки має бути від 0 до 100"
    except (ValueError, TypeError, InvalidOperation):
        return "Некоректне значення відсотка"

    return None

#CRUD for Customer Cards
class CustomerCardListAPIView(APIView):
    permission_classes = [IsManager | IsCashier]

    def get(self, request):
        search = request.GET.get('search', '').strip()

        query = """
            SELECT card_number, cust_surname, cust_name, cust_patronymic,
                   phone_number, city, street, zip_code, percent
            FROM CustomerCard
            WHERE 1 = 1
        """
        params = []
        if search:
            query += " AND LOWER(cust_surname) LIKE LOWER(%s)"
            params.append(f"{search}%")

        query += " ORDER BY cust_surname ASC"

        with connection.cursor() as cursor:
            cursor.execute(query, params)
            return Response(dictfetchall(cursor), status=status.HTTP_200_OK)

    def post(self, request):
        data = request.data

        error = validate_customer_data(data)
        if error:
            return Response({"error": error}, status=status.HTTP_400_BAD_REQUEST)

        with connection.cursor() as cursor:
            try:
                # генерація ID
                cursor.execute("SELECT MAX(CAST(card_number AS NUMERIC)) FROM CustomerCard")
                max_id = cursor.fetchone()[0]
                next_id = str((max_id or 0) + 1).zfill(13)

                cursor.execute("""
                    INSERT INTO CustomerCard (
                        card_number, cust_surname, cust_name, cust_patronymic,
                        phone_number, city, street, zip_code, percent
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, [
                    next_id, data.get('cust_surname'), data.get('cust_name'),
                    data.get('cust_patronymic'), data.get('phone_number'), data.get('city'),
                    data.get('street'), data.get('zip_code'), data.get('percent')
                ])
                return Response({"message": "Карту успішно створено"}, status=status.HTTP_201_CREATED)
            except IntegrityError:
                return Response({"error": "Картка з таким номером вже існує"}, status=status.HTTP_400_BAD_REQUEST)

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
        data = request.data

        error = validate_customer_data(data)
        if error:
            return Response({"error": error}, status=status.HTTP_400_BAD_REQUEST)

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

                if cursor.rowcount == 0:
                    return Response({"detail": "Карту з таким номером не знайдено."}, status=status.HTTP_404_NOT_FOUND)

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
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')

        query = """
            SELECT c.check_number, c.print_date, c.sum_total, c.vat, 
                   e.empl_surname, e.empl_name, card.percent
            FROM StoreCheck c
            JOIN Employee e ON c.id_employee = e.id_employee
            LEFT JOIN CustomerCard card ON c.card_number = card.card_number
            WHERE 1 = 1
        """
        params = []

        if start_date:
            query += " AND c.print_date >= %s"
            params.append(start_date + " 00:00:00")
        if end_date:
            query += " AND c.print_date <= %s"
            params.append(end_date + " 23:59:59")

        query += " ORDER BY c.print_date DESC"

        with connection.cursor() as cursor:
            cursor.execute(query, params)
            return Response(dictfetchall(cursor), status=status.HTTP_200_OK)

    @transaction.atomic
    def post(self, request):
        if request.user.empl_role != 'Касир':
            return Response({"detail": "Пробивати чеки можуть лише касири"}, status=status.HTTP_403_FORBIDDEN)

        data = request.data
        items_list = data.get('items', [])

        with connection.cursor() as cursor:
            try:
                cursor.execute("SELECT MAX(CAST(check_number AS NUMERIC)) FROM StoreCheck")
                max_id = cursor.fetchone()[0]

                next_check_int = int(max_id) + 1 if max_id else 1000000000
                check_number = str(next_check_int).zfill(10)

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

    @transaction.atomic
    def delete(self, request, check_number):
        if request.user.empl_role != 'Менеджер':
            return Response({"detail": "Видаляти чеки можуть лише менеджери."}, status=status.HTTP_403_FORBIDDEN)

        return_items = request.query_params.get('return_items', 'false') == 'true'

        with connection.cursor() as cursor:
            try:
                if return_items:
                    cursor.execute("SELECT upc, product_number FROM Sale WHERE check_number = %s", [check_number])
                    items_in_check = cursor.fetchall()
                    for item in items_in_check:
                        cursor.execute("UPDATE StoreProduct SET products_number = products_number + %s WHERE upc = %s",
                                       [item[1], item[0]])

                cursor.execute("DELETE FROM Sale WHERE check_number = %s", [check_number])
                cursor.execute("DELETE FROM StoreCheck WHERE check_number = %s", [check_number])

                return Response({"message": "Чек видалено"}, status=status.HTTP_200_OK)
            except Exception as e:
                return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

def get_next_upc(is_promo, upc_prom=None):
    if is_promo and upc_prom:
        try:
            return str(int(upc_prom) + 1)
        except ValueError:
            pass

    with connection.cursor() as cursor:
        try:
            cursor.execute("SELECT upc FROM StoreProduct")
            rows = cursor.fetchall()

            max_odd_upc = 9999
            max_even_upc = 10000

            for row in rows:
                try:
                    num = int(row[0])
                    if num % 2 != 0 and num > max_odd_upc:
                        max_odd_upc = num
                    elif num % 2 == 0 and num > max_even_upc:
                        max_even_upc = num
                except (ValueError, TypeError):
                    pass

            if not is_promo:
                return str(max_odd_upc + 2)
            else:
                return str(max_even_upc + 2)

        except Exception:
            return "10002" if is_promo else "10001"

#CRUD for store products
class StoreProductListAPIView(APIView):
    permission_classes = [IsManager | IsCashier]

    def get(self, request):
        search = request.GET.get('search', '').strip()
        sort_by = request.GET.get('sort', 'name')
        promo_filter = request.GET.get('promo', 'all')

        query = """
            SELECT sp.upc, sp.upc_prom, p.id_product, p.product_name, sp.selling_price,
                   sp.products_number, sp.promotional_product
            FROM StoreProduct sp
            JOIN Product p ON sp.id_product = p.id_product
            WHERE 1 = 1
        """
        params = []

        if search:
            query += " AND (LOWER(p.product_name) LIKE LOWER(%s) OR sp.upc LIKE %s)"
            params.extend([f"%{search}%", f"%{search}%"])

        if promo_filter == 'true':
            query += " AND sp.promotional_product = TRUE"
        elif promo_filter == 'false':
            query += " AND sp.promotional_product = FALSE"

            # Сортування за кількістю або за назвою
        if sort_by == 'qty':
            query += " ORDER BY sp.products_number ASC"
        else:
            query += " ORDER BY p.product_name ASC"

        with connection.cursor() as cursor:
            cursor.execute(query, params)
            return Response(dictfetchall(cursor), status=status.HTTP_200_OK)

    @transaction.atomic
    def post(self, request):
        if request.user.empl_role != 'Менеджер':
            return Response({"detail": "Додавати товари в магазин можуть лише менеджери"}, status=status.HTTP_403_FORBIDDEN)

        data = request.data
        id_product = data.get('id_product')
        promotional_product = str(data.get('promotional_product')).lower() == 'true'
        upc_prom = data.get('upc_prom')
        selling_price = data.get('selling_price')

        req_qty = int(data.get('products_number', 0))

        if promotional_product and not upc_prom:
            return Response({"error": "Неможливо створити акцію: відсутній оригінальний UPC звичайного товару!"},
                            status=status.HTTP_400_BAD_REQUEST)

        upc = data.get('upc')
        if not upc:
            upc = get_next_upc(promotional_product, upc_prom)
        else:
            try:
                upc_int = int(upc)
                if promotional_product and upc_int % 2 != 0:
                    return Response({"error": "Акційний товар повинен мати ПАРНИЙ UPC!"}, status=status.HTTP_400_BAD_REQUEST)
                if not promotional_product and upc_int % 2 == 0:
                    return Response({"error": "Звичайний товар повинен мати НЕПАРНИЙ UPC!"}, status=status.HTTP_400_BAD_REQUEST)
            except ValueError:
                pass

        with connection.cursor() as cursor:
            try:
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

                    # Автоматична знижка 20% та перевірка кількості
                if promotional_product and upc_prom:
                    cursor.execute("SELECT selling_price, products_number FROM StoreProduct WHERE upc = %s", [upc_prom])
                    base_product_row = cursor.fetchone()

                    if base_product_row:
                        base_price = float(base_product_row[0])
                        base_qty = int(base_product_row[1])
                        selling_price = base_price * 0.8

                        # Перевірка кількості
                        if req_qty > base_qty:
                            return Response({
                                "error": f"Кількість акційного товару ({req_qty}) не може бути більшою за залишок звичайного ({base_qty})!"
                            }, status=status.HTTP_400_BAD_REQUEST)

                         # СПИСАННЯ зі звичайного товару
                        cursor.execute("""
                            UPDATE StoreProduct
                            SET products_number = products_number - %s
                            WHERE upc = %s
                        """, [req_qty, upc_prom])

                cursor.execute("""
                    INSERT INTO StoreProduct (upc, upc_prom, id_product, selling_price, products_number, promotional_product)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, [ upc, upc_prom, id_product, selling_price, data.get('products_number'), promotional_product])

                return Response({"message": "Товар успішно додано на полиці магазину"}, status=status.HTTP_201_CREATED)
            except IntegrityError as e:
                error_msg = str(e).lower()

                if "unique" in error_msg or "primary key" in error_msg:
                    return Response({"error": f"Товар з UPC «{data.get('upc')}» вже існує в базі! Придумайте інший."}, status=status.HTTP_400_BAD_REQUEST)

                elif "upc_prom" in error_msg or "foreign key" in error_msg:
                    return Response({"error": "Помилка зв'язку: Базовий товар не знайдено у базі."}, status=status.HTTP_400_BAD_REQUEST)

                else:
                    return Response({"error": f"Помилка бази даних: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)
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

    @transaction.atomic
    def put(self, request, upc):
        if request.user.empl_role != 'Менеджер':
            return Response({"detail": "Редагування доступне лише менеджерам"}, status=status.HTTP_403_FORBIDDEN)

        data = request.data

        validation_error = validate_store_product_data(data)
        if validation_error:
            return Response({"error": validation_error}, status=status.HTTP_400_BAD_REQUEST)

        is_write_off = data.get('is_write_off', False)

        with connection.cursor() as cursor:
            try:
                cursor.execute("SELECT products_number, promotional_product, upc_prom FROM StoreProduct WHERE upc = %s", [upc])
                current_prod = cursor.fetchone()

                if not current_prod:
                    return Response({"detail": "Товар не знайдено для оновлення"}, status=status.HTTP_404_NOT_FOUND)

                old_qty = int(current_prod[0])
                is_promo = current_prod[1]
                upc_prom = current_prod[2]
                new_qty = int(data.get('products_number', old_qty))

                if is_promo and upc_prom and not is_write_off:
                    qty_diff = new_qty - old_qty

                    if qty_diff != 0:
                        cursor.execute(" SELECT products_number FROM StoreProduct WHERE upc = %s", [upc_prom])
                        base_prod = cursor.fetchone()

                        if base_prod:
                            base_qty = int(base_prod[0])

                            if qty_diff > 0 and qty_diff > base_qty:
                                return Response({"error": f"Недостатньо звичайного товару для збільшення акційної партії. Доступно: {base_qty} од."}, status=status.HTTP_400_BAD_REQUEST)

                            cursor.execute("""
                                UPDATE StoreProduct
                                SET products_number = products_number - %s
                                WHERE upc = %s
                            """, [qty_diff, upc_prom])

                final_selling_price = data.get('selling_price')

                if is_promo and upc_prom:
                    cursor.execute("SELECT selling_price FROM StoreProduct WHERE upc = %s", [upc_prom])
                    base_price_row = cursor.fetchone()
                    if base_price_row:
                        final_selling_price = float(base_price_row[0]) * 0.8

                cursor.execute("""
                    UPDATE StoreProduct
                    SET selling_price = %s, products_number = %s, promotional_product = %s
                    WHERE upc = %s
                """, [
                            final_selling_price,
                            new_qty,
                            data.get('promotional_product', False),
                            upc])

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

# Reports
class TotalSalesSummaryAPIView(APIView):
    """
    Звіт: Загальна сума продажів за період часу + список проданих товарів.
    - всі касири, якщо id_employee не передано
    - конкретний касир, якщо передано id_employee
    """
    permission_classes = [IsManager]

    def get(self, request):
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')
        id_employee = request.query_params.get('id_employee')

        if not start_date or not end_date:
            return Response({"error": "Вкажіть параметри start_date та end_date (формат РРРР-ММ-ДД)"}, status=status.HTTP_400_BAD_REQUEST)

        end_date_full = f"{end_date} 23:59:59"

        with connection.cursor() as cursor:
            if id_employee:
                cursor.execute("""
                    SELECT COALESCE(SUM(sum_total), 0) as total_revenue, 
                           COUNT(check_number) as total_checks_printed
                    FROM StoreCheck
                    WHERE print_date >= %s AND print_date <= %s AND id_employee = %s
                """, [start_date, end_date_full, id_employee])
                summary_row = dictfetchall(cursor)[0]

                cursor.execute("""
                    SELECT p.product_name, sp.upc, 
                           SUM(s.product_number) as total_quantity,
                           SUM( 
                               ROUND(
                                   (s.product_number * s.selling_price) / 
                                   (SELECT SUM(s2.product_number * s2.selling_price) FROM Sale s2 WHERE s2.check_number = c.check_number) 
                                   * c.sum_total
                               , 4)
                           ) as total_product_revenue
                    FROM Sale s
                    JOIN StoreCheck c ON s.check_number = c.check_number
                    JOIN StoreProduct sp ON s.upc = sp.upc
                    JOIN Product p ON sp.id_product = p.id_product
                    WHERE c.print_date >= %s AND c.print_date <= %s AND c.id_employee = %s
                    GROUP BY sp.upc, p.product_name
                    ORDER BY total_product_revenue DESC
                """, [start_date, end_date_full, id_employee])
                products_rows = dictfetchall(cursor)

            else:
                cursor.execute("""
                    SELECT COALESCE(SUM(sum_total), 0) as total_revenue, 
                           COUNT(check_number) as total_checks_printed
                    FROM StoreCheck
                    WHERE print_date >= %s AND print_date <= %s
                """, [start_date, end_date_full])
                summary_row = dictfetchall(cursor)[0]

                cursor.execute("""
                    SELECT p.product_name, sp.upc, 
                           SUM(s.product_number) as total_quantity,
                           SUM( 
                               ROUND(
                                   (s.product_number * s.selling_price) / 
                                   (SELECT SUM(s2.product_number * s2.selling_price) FROM Sale s2 WHERE s2.check_number = c.check_number) 
                                   * c.sum_total
                               , 4)
                           ) as total_product_revenue
                    FROM Sale s
                    JOIN StoreCheck c ON s.check_number = c.check_number
                    JOIN StoreProduct sp ON s.upc = sp.upc
                    JOIN Product p ON sp.id_product = p.id_product
                    WHERE c.print_date >= %s AND c.print_date <= %s
                    GROUP BY sp.upc, p.product_name
                    ORDER BY total_product_revenue DESC
                """, [start_date, end_date_full])
                products_rows = dictfetchall(cursor)

        result = {
            "total_revenue": summary_row["total_revenue"],
            "total_checks_printed": summary_row["total_checks_printed"],
            "sold_products": products_rows
        }

        return Response(result, status=status.HTTP_200_OK)

class ProductSalesSummaryAPIView(APIView):
    """
    Звіт: Визначити загальну кількість проданих одиниць певного товару за певний період часу.
    Шукаємо за id_product, щоб звести разом продажі як звичайного, так і акційного варіантів цього товару.
    """
    permission_classes = [IsManager]

    def get(self, request):
        id_product = request.query_params.get('id_product')
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')

        if not id_product or not start_date or not end_date:
            return Response({"error": "Вкажіть id_product, start_date та end_date"}, status=status.HTTP_400_BAD_REQUEST)

        end_date_full = f"{end_date} 23:59:59"

        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT p.id_product, p.product_name, COALESCE(SUM(s.product_number), 0) as total_items_sold
                FROM Sale s
                JOIN StoreCheck c ON s.check_number = c.check_number
                JOIN StoreProduct sp ON s.upc = sp.upc
                JOIN Product p ON sp.id_product = p.id_product
                WHERE p.id_product = %s
                AND c.print_date >= %s
                AND c.print_date <= %s
                GROUP BY p.id_product, p.product_name
            """, [id_product, start_date, end_date_full])

            row = dictfetchall(cursor)

        if not row:
            return Response(
                {"id_product": id_product, "total_items_sold": 0, "message": "Товар не продавався у вказаний період"}, status=status.HTTP_200_OK)

        return Response(row[0], status=status.HTTP_200_OK)

class TeamSpecificReportsAPIView(APIView):
    """
    Звіт: Повний комплексний звіт з усіх запитів для конкретного члена команди.
    Очікує параметр у форматі: ?author=olya
    """
    permission_classes = [IsManager]

    def get(self, request):
        author = request.query_params.get('author', '').lower()

        if author == 'olha_mykhailyk':
            return self.get_olyaMy_full_report()
        elif author == 'olha_marushchenko':
            return self.get_olhaMa_queries()
        elif author == 'daria_melnyk':
            category_id = request.query_params.get('category_id', 1)
            return self.get_dariaMe_queries(category_id)

        return Response(
            {"error": "Вкажіть дійсного автора"},
            status=status.HTTP_400_BAD_REQUEST
        )

    def get_olyaMy_full_report(self, request):
        min_revenue_str = request.query_params.get('min_revenue', '0')
        try:
            min_revenue = float(min_revenue_str)
        except ValueError:
            min_revenue = 0.0
        with connection.cursor() as cursor:
            # ЗАПИТ 1: Виручка та кількість проданих одиниць за категоріями з відсіканням за мінімальною виручкою
            cursor.execute("""
                SELECT 
                    c.category_name AS "Назва категорії",
                    SUM(s.product_number) AS "Продано одиниць",
                    SUM(s.product_number * s.selling_price) AS "Загальна виручка"
                FROM Category c
                INNER JOIN Product p ON c.category_number = p.category_number
                INNER JOIN StoreProduct sp ON p.id_product = sp.id_product
                INNER JOIN Sale s ON sp.upc = s.upc
                GROUP BY c.category_name
                HAVING SUM(s.product_number * s.selling_price) >= %s
                ORDER BY "Загальна виручка" DESC;
            """, [min_revenue])
            category_sales = dictfetchall(cursor)

            # ЗАПИТ 2: Реляційне ділення (чеки з усіма акційними товарами)
            cursor.execute("""
                SELECT 
                    c.check_number AS "Номер чеку",
                    c.print_date AS "Дата чеку",
                    c.sum_total AS "Сума чеку",
                    e.empl_surname AS "Прізвище касира"
                FROM StoreCheck c
                INNER JOIN Employee e ON c.id_employee = e.id_employee
                WHERE NOT EXISTS (SELECT sp.upc
                FROM StoreProduct sp
                WHERE sp.promotional_product = TRUE
                AND NOT EXISTS (SELECT s.upc
                FROM Sale s
                WHERE s.upc = sp.upc
                AND s.check_number = c.check_number));
            """)
            all_promo_checks = dictfetchall(cursor)

        # Формуємо єдину відповідь, де кожен запит має свій чіткий ключ
        combined_data = {
            "author": "Ольга Михайлик",
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "category_sales_summary": category_sales,
            "checks_with_all_promo_items": all_promo_checks
        }

        return Response(combined_data, status=status.HTTP_200_OK)

    def get_olhaMa_queries(self):
        date_from = self.request.query_params.get("date_from")
        date_to = self.request.query_params.get("date_to")

        if not date_from or not date_to:
            return Response(
                {"error": "Вкажіть обидві дати: date_from та date_to (формат РРРР-ММ-ДД)"},
                status=status.HTTP_400_BAD_REQUEST
            )

        date_to_full = f"{date_to} 23:59:59"
        with connection.cursor() as cursor:
            # ЗАПИТ 1: Кількість чеків, створених кожним касиром
            cursor.execute("""
                          SELECT e.id_employee,
                               e.empl_surname,
                               e.empl_name,
                               COUNT(DISTINCT sc.check_number) AS total_checks,
                               SUM(s.product_number) AS total_items_sold,
                               SUM(s.selling_price * s.product_number) AS total_revenue
                          FROM Employee e
                              JOIN StoreCheck sc ON sc.id_employee = e.id_employee
                              JOIN Sale s ON s.check_number = sc.check_number
                          WHERE sc.print_date BETWEEN %s AND %s
                          GROUP BY e.id_employee, e.empl_surname, e.empl_name
                          HAVING COUNT(DISTINCT sc.check_number) > 0
                          ORDER BY total_revenue DESC;
                           """,  [date_from, date_to_full])
            cashier_checks = dictfetchall(cursor)
            # ЗАПИТ 2: Товари, які купували ВСІ клієнти з картками
            cursor.execute("""
                           SELECT DISTINCT p.product_name,
                                           p.characteristics,
                                           sp.selling_price
                           FROM Product p
                           JOIN StoreProduct sp ON p.id_product = sp.id_product
                                WHERE NOT EXISTS (SELECT cc.card_number
                                FROM CustomerCard cc
                                    WHERE NOT EXISTS (SELECT sc.check_number
                                    FROM StoreCheck sc
                                     JOIN Sale s ON sc.check_number = s.check_number
                                     WHERE s.upc = sp.upc AND sc.card_number = cc.card_number));
                           """)
            products_for_card_holders = dictfetchall(cursor)

        combined_data = {
            "author": "Ольга Марущенко",
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "cashier_check_counts": cashier_checks,
            "products_bought_by_all_card_holders": products_for_card_holders
        }
        return Response(combined_data, status=status.HTTP_200_OK)

    def get_dariaMe_queries(self, category_id):
        with connection.cursor() as cursor:
            # ЗАПИТ 1: Виручка касирів за конкретною категорією
            cursor.execute("""
                SELECT e.empl_surname AS "Прізвище", 
                       e.empl_name AS "Ім'я", 
                       SUM(s.product_number * s.selling_price) AS "Виручка з категорії"
                FROM Employee e
                INNER JOIN StoreCheck sc ON e.id_employee = sc.id_employee
                INNER JOIN Sale s ON sc.check_number = s.check_number
                INNER JOIN StoreProduct sp ON s.upc = sp.upc
                INNER JOIN Product p ON sp.id_product = p.id_product
                WHERE p.category_number = %s
                GROUP BY e.id_employee, e.empl_surname, e.empl_name
                ORDER BY "Виручка з категорії" DESC;
            """, [category_id])
            revenue_by_category = dictfetchall(cursor)

            # ЗАПИТ 2: Товари, які продавали абсолютно всі касири
            cursor.execute("""
                SELECT p.product_name AS "Назва товару", 
                       p.manufacturer AS "Виробник"
                FROM Product p
                WHERE NOT EXISTS (
                    SELECT e.id_employee
                    FROM Employee e
                    WHERE e.empl_role = 'Касир'
                    AND NOT EXISTS (
                        SELECT s.upc
                        FROM Sale s
                        INNER JOIN StoreCheck sc ON s.check_number = sc.check_number
                        INNER JOIN StoreProduct sp ON s.upc = sp.upc
                        WHERE sc.id_employee = e.id_employee 
                          AND sp.id_product = p.id_product
                    )
                );
            """)
            sold_by_all = dictfetchall(cursor)

        combined_data = {
            "author": "Дар'я Мельник",
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "revenue_by_category": revenue_by_category,
            "products_sold_by_all_cashiers": sold_by_all
        }
        return Response(combined_data, status=status.HTTP_200_OK)
