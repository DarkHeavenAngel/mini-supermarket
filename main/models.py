from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator

from django.db import models
from django.db.models import Max, IntegerField
from django.db.models import CheckConstraint, Q
from django.db.models.functions import Cast

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from datetime import date
from django.utils import timezone

#Validators
phone_validator = RegexValidator(regex=r'^\+380', message="Номер телефону потрібно ввести у форматі: +38012345678")

def validate_employee_age(born):
    today = date.today()
    age = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
    if age < 18:
        raise ValidationError("Вік працівника повинен становити не менше 18 років")

class EmployeeManager(BaseUserManager):
    def create_user(self, id_employee, password=None, **extra_fields):
        if not id_employee:
            raise ValueError('Необхідно ввести ідентифікаційний номер співробітника')
        user = self.model(id_employee=id_employee, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, id_employee, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        return self.create_user(id_employee, password, **extra_fields)

class Employee(AbstractBaseUser, PermissionsMixin):
    ROLE_CHOICES = [
        ('Менеджер', 'Менеджер'),
        ('Касир', 'Касир')
    ]

    id_employee = models.CharField(primary_key=True, max_length=10)
    empl_surname = models.CharField('Прізвище', max_length=50)
    empl_name = models.CharField('Ім*я', max_length=50)
    empl_patronymic = models.CharField('Побатькові', max_length=50, blank=True, null=True)
    empl_role = models.CharField('Роль', max_length=10, choices=ROLE_CHOICES)
    salary = models.DecimalField('Заробітна плата', decimal_places=4, max_digits=13)
    date_of_birth = models.DateField('Дата народження', validators=[validate_employee_age])
    date_of_start = models.DateField('Дата початку роботи')
    phone_number = models.CharField('Номер телефону', max_length=13, validators=[phone_validator])
    city = models.CharField('Місто', max_length=50)
    street = models.CharField('Вулиця', max_length=50)
    zip_code = models.CharField('Поштовий індекс', max_length=9)

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    objects = EmployeeManager()

    USERNAME_FIELD = 'id_employee'
    REQUIRED_FIELDS = [
        'empl_surname', 'empl_name', 'empl_role',
        'salary', 'date_of_birth', 'date_of_start',
        'phone_number', 'city', 'street', 'zip_code'
    ]

    def __str__(self):
        return f"{self.empl_surname} {self.empl_name} ({self.empl_role})"

    class Meta:
        db_table = 'Employee'
        verbose_name = 'Працівник'
        verbose_name_plural = 'Працівники'
        constraints = [
            CheckConstraint(condition=Q(salary__gte=0), name='salary_non_negative'),
            CheckConstraint(condition=Q(phone_number__startswith='+380'), name='empl_phone_number_startswith_380')
        ]

class CustomerCard(models.Model):
    card_number = models.CharField(primary_key=True, max_length=13)
    cust_surname = models.CharField('Прізвище', max_length=50)
    cust_name = models.CharField('Ім*я', max_length=50)
    cust_patronymic = models.CharField('Побатькові', max_length=50, blank=True, null=True)
    phone_number = models.CharField('Номер телефону', max_length=13, validators=[phone_validator])
    city = models.CharField('Місто', max_length=50, blank=True, null=True)
    street = models.CharField('Вулиця', max_length=50, blank=True, null=True)
    zip_code = models.CharField('Поштовий індекс', max_length=9, blank=True, null=True)
    percent = models.IntegerField('Відсоток знижки')

    def __str__(self):
        return self.card_number

    class Meta:
        db_table = 'CustomerCard'
        verbose_name = 'Карта клієнта'
        verbose_name_plural = 'Карти клієнтів'
        constraints = [
            CheckConstraint(condition=Q(percent__gte=0), name='percent_non_negative'),
            CheckConstraint(condition=Q(phone_number__startswith='+380'), name='phone_number_startswith_380')
        ]

class Check(models.Model):
    check_number = models.CharField(primary_key=True, max_length=10, blank=True)
    id_employee = models.ForeignKey(Employee, on_delete=models.PROTECT, verbose_name='Код працівника', db_column='id_employee')
    card_number = models.ForeignKey(CustomerCard, on_delete=models.PROTECT, verbose_name='Номер карти лояльності', blank=True, null=True, db_column='card_number')
    print_date = models.DateTimeField('Дата створення', default=timezone.now)
    sum_total = models.DecimalField('Сума', decimal_places=4, max_digits=13, default=0)
    vat = models.DecimalField('ПДВ', decimal_places=4, max_digits=13, default=0)

    # автоматизація номеру чеку
    def save(self, *args, **kwargs):
        if not self.check_number:
            max_check = Check.objects.annotate(
                check_int=Cast('check_number', output_field=IntegerField())
            ).aggregate(Max('check_int'))['check_int__max']

            next_number = (max_check or 0) + 1
            self.check_number = str(next_number).zfill(10)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.check_number

    class Meta:
        db_table = 'StoreCheck'
        verbose_name = 'Чек'
        verbose_name_plural = 'Чеки'
        constraints = [
            CheckConstraint(condition=Q(sum_total__gte=0), name='sum_total_non_negative'),
            CheckConstraint(condition=Q(vat__gte=0), name='vat_non_negative'),
        ]

class Category(models.Model):
    category_number = models.AutoField(primary_key=True, verbose_name='Номер категорії')
    category_name = models.CharField('Назва', max_length=50)

    def __str__(self):
        return self.category_name

    class Meta:
        db_table = 'Category'
        verbose_name = 'Категорія'
        verbose_name_plural = 'Категорії'

class Product(models.Model):
    id_product = models.AutoField(primary_key=True, verbose_name='ID продукту')
    category_number = models.ForeignKey(Category, on_delete=models.PROTECT, verbose_name='Номер категорії', db_column='category_number')
    product_name = models.CharField('Назва', max_length=50)
    characteristics = models.CharField('Опис', max_length=100)
    manufacturer = models.CharField('Виробник', max_length=100)

    def __str__(self):
        return self.product_name

    class Meta:
        db_table = 'Product'
        verbose_name = 'Продукт'
        verbose_name_plural = 'Продукти'

class StoreProduct(models.Model):
    upc = models.CharField(primary_key=True, max_length=12)
    upc_prom = models.ForeignKey('self', on_delete=models.SET_NULL, blank=True, null=True, db_column='upc_prom', related_name='promotional_copies')
    id_product = models.ForeignKey(Product, on_delete=models.PROTECT, db_column='id_product')
    selling_price = models.DecimalField('Ціна', decimal_places=4, max_digits=13, default=0)
    products_number = models.IntegerField('Кількість одиниць')
    promotional_product = models.BooleanField('Акційний продукт', default=False)

    def __str__(self):
        if self.promotional_product:
            status = "Акція"
        else:
            status = "Звичайний"
        return f"UPC: {self.upc} - {self.id_product.product_name} ({status})"

    class Meta:
        db_table = 'StoreProduct'
        verbose_name = 'Наявний продукт'
        verbose_name_plural = 'Наявні продукти'
        constraints = [
            CheckConstraint(condition=Q(selling_price__gte=0), name='selling_price_non_negative'),
            CheckConstraint(condition=Q(products_number__gte=0), name='products_number_non_negative'),
        ]

class Sale(models.Model):
    upc = models.ForeignKey(StoreProduct, on_delete=models.PROTECT, db_column='upc')
    check_number = models.ForeignKey(Check, on_delete=models.CASCADE, db_column='check_number')
    product_number = models.IntegerField('Кількість одиниць')
    selling_price = models.DecimalField('Ціна', decimal_places=4, max_digits=13)

    class Meta:
        db_table = 'Sale'
        verbose_name = 'Продано'
        verbose_name_plural = 'Продано'
        constraints = [
            models.UniqueConstraint(fields=['upc', 'check_number'], name='unique_sale_item'),
            CheckConstraint(condition=Q(product_number__gte=0), name='sale_product_number_non_negative'),
            CheckConstraint(condition=Q(selling_price__gte=0), name='sale_selling_price_non_negative'),
        ]