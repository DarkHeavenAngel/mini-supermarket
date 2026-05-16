from decimal import Decimal
from django.db import connection, transaction
from datetime import datetime

def store_product(upc, id_product, selling_price, products_number, is_promotional=False, upc_prom=None):
    with connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM StoreProduct WHERE id_product = %s", [id_product])
        count = cursor.fetchone()[0]

        if count >= 2:
            return {
                "success": False,
                "error": 'There is already two records for this product'
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
        subtotal = Decimal('0.0')

        for item in items_list:
            cursor.execute("SELECT selling_price FROM StoreProduct WHERE upc = %s", [item['upc']])
            price = cursor.fetchone()[0]
            subtotal += price * Decimal(item['qty'])

        discount = Decimal('0.0')
        if card_number:
            cursor.execute("SELECT percent FROM CustomerCard WHERE card_number = %s", [card_number])
            card_row = cursor.fetchone()
            if card_row:
                discount = Decimal(card_row[0])

        multiplier = (Decimal('100') - discount) / Decimal('100')
        final_sum = subtotal * multiplier
        vat_amount = final_sum * Decimal('0.2')

        current_time = datetime.now()

        cursor.execute("""
            INSERT INTO StoreCheck (check_number, id_employee, card_number, print_date, sum_total, vat)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, [check_number, id_employee, card_number, current_time, final_sum, vat_amount])

        for item in items_list:
            cursor.execute("SELECT selling_price FROM StoreProduct WHERE upc = %s", [item['upc']])
            price = cursor.fetchone()[0]

            cursor.execute("""
                INSERT INTO Sale (upc, check_number, product_number, selling_price)
                VALUES (%s, %s, %s, %s)
            """, [item['upc'], check_number, item['qty'], price])

    return {"success": True, "message": 'Check added successfully'}

