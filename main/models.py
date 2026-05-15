from django.db import models
from django.db.models import CheckConstraint, Q
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin

class EmployeeManager(BaseUserManager):
    def create_user(self, id_employee, password=None, **extra_fields):
        if not id_employee:
            raise ValueError('Employee ID is required')
        user = self.model(id_employee=id_employee, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, id_employee, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        return self.create_user(id_employee, password, **extra_fields)

class Employee(AbstractBaseUser, PermissionsMixin):
    id_employee = models.CharField(primary_key=True, max_length=10)
    empl_surname = models.CharField('Прізвище', max_length=50)
    empl_name = models.CharField('Ім*я', max_length=50)
    empl_patronymic = models.CharField('Побатькові', max_length=50, blank=True, null=True)
    empl_role = models.CharField('Роль', max_length=10)
    salary = models.DecimalField('Заробітна плата', decimal_places=4, max_digits=13)
    date_of_birth = models.DateField('Дата народження')
    date_of_start = models.DateField('Дата початку роботи')
    phone_number = models.CharField('Номер телефону', max_length=13)
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

    class Meta:
        db_table = 'Employee'
        constraints = [
            CheckConstraint(check=Q(salary__gte=0), name='salary_non_negative')
        ]

class CustomerCard(models.Model):
    card_number = models.CharField(primary_key=True, max_length=13)
    cust_surname = models.CharField('Прізвище', max_length=50)
    cust_name = models.CharField('Ім*я', max_length=50)
    cust_patronymic = models.CharField('Побатькові', max_length=50, blank=True, null=True)
    phone_number = models.CharField('Номер телефону', max_length=13)
    city = models.CharField('Місто', max_length=50, blank=True, null=True)
    street = models.CharField('Вулиця', max_length=50, blank=True, null=True)
    zip_code = models.CharField('Поштовий індекс', max_length=9, blank=True, null=True)
    percent = models.IntegerField('Відсоток знижки')

    def __str__(self):
        return self.card_number

    class Meta:
        db_table = 'CustomerCard'
        constraints = [
            CheckConstraint(check=Q(percent__gte=0), name='percent_non_negative')
        ]

class Check(models.Model):
    check_number = models.CharField(primary_key=True, max_length=10)
    id_employee = models.ForeignKey(Employee, on_delete=models.DO_NOTHING, verbose_name='Код працівника', db_column='id_employee')
    card_number = models.ForeignKey(CustomerCard, on_delete=models.DO_NOTHING, verbose_name='Номер карти лояльності', blank=True, null=True, db_column='card_number')
    print_date = models.DateTimeField('Дата створення')
    sum_total = models.DecimalField('Сума', decimal_places=4, max_digits=13)
    vat = models.DecimalField('ПДВ', decimal_places=4, max_digits=13)

    def __str__(self):
        return self.check_number

    class Meta:
        db_table = 'Check'
        constraints = [
            CheckConstraint(check=Q(sum_total__gte=0), name='sum_total_non_negative'),
            CheckConstraint(check=Q(vat__gte=0), name='vat_non_negative'),
        ]

class Category(models.Model):
    category_number = models.IntegerField(primary_key=True)
    category_name = models.CharField('Назва', max_length=50)

    def __str__(self):
        return self.category_name

    class Meta:
        db_table = 'Category'

class Product(models.Model):
    id_product = models.IntegerField(primary_key=True)
    category_number = models.ForeignKey(Category, on_delete=models.DO_NOTHING, verbose_name='Номер категорії', db_column='category_number')
    product_name = models.CharField('Назва', max_length=50)
    characteristics = models.CharField('Опис', max_length=100)

    def __str__(self):
        return self.product_name

    class Meta:
        db_table = 'Product'

class StoreProduct(models.Model):
    upc = models.CharField(primary_key=True, max_length=12)
    upc_prom = models.ForeignKey('self', on_delete=models.SET_NULL, blank=True, null=True, db_column='upc_prom')
    id_product = models.ForeignKey(Product, on_delete=models.DO_NOTHING, db_column='id_product')
    selling_price = models.DecimalField('Ціна', decimal_places=4, max_digits=13)
    products_number = models.IntegerField('Кількість одиниць')
    promotional_product = models.BooleanField('Акційний продукт')

    class Meta:
        db_table = 'StoreProduct'
        constraints = [
            CheckConstraint(check=Q(selling_price__gte=0), name='selling_price_non_negative'),
            CheckConstraint(check=Q(products_number__gte=0), name='products_number_non_negative'),
        ]

class Sale(models.Model):
    upc = models.ForeignKey(StoreProduct, on_delete=models.DO_NOTHING, db_column='upc')
    check_number = models.ForeignKey(Check, on_delete=models.CASCADE, db_column='check_number')
    product_number = models.IntegerField('Кількість одиниць')
    selling_price = models.DecimalField('Ціна', decimal_places=4, max_digits=13)

    class Meta:
        db_table = 'Sale'
        unique_together = (('upc', 'check_number'),)
        constraints = [
            CheckConstraint(check=Q(product_number__gte=0), name='sale_product_number_non_negative'),
            CheckConstraint(check=Q(selling_price__gte=0), name='sale_selling_price_non_negative'),
        ]
