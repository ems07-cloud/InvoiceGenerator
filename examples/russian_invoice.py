# -*- coding: utf-8 -*-
"""Пример: счёт на оплату с НДС и QR-кодом. Реквизиты выдуманные, но корректные по контрольным цифрам."""
import datetime
import sys

from InvoiceGenerator.api import Client, Creator, Invoice, Item, Provider
from InvoiceGenerator.ru import RussianInvoice

provider = Provider(
    "ООО «Ромашка»", address="ул. Лесная, д. 5, офис 12", city="г. Москва", zip_code="125047",
    inn="7709999995", kpp="770901001", phone="+7 999 000-00-00",
    bank_name="АО «Демо Банк», г. Москва", bik="049999001",
    bank_account="40702810800000012345", corr_account="30101810900000000001",
    note="Счёт действителен в течение 7 дней. Оплата данного счёта означает согласие с условиями оказания услуг.",
)
client = Client("ИП Сидоров Сидор Сидорович", inn="500999999900", city="г. Химки",
                address="ул. Победы, д. 1")

invoice = Invoice(client, provider, Creator("Иванов И. И."))
invoice.number = 17
invoice.date = datetime.date(2026, 10, 7)
invoice.payback = datetime.date(2026, 10, 14)
invoice.basis = "Договор № 12/26 от 1 октября 2026 г."
invoice.director = "Иванов И. И."
invoice.accountant = "Смирнова А. В."
invoice.add_item(Item(1, 45000, "Разработка интернет-магазина на WordPress: дизайн, каталог, корзина", unit="усл.", tax=22))
invoice.add_item(Item(120, 150, "Наполнение каталога товарами", unit="шт", tax=22))
invoice.add_item(Item(1, 9900, "Подключение онлайн-оплаты и СБП", unit="усл.", tax=22))
invoice.add_item(Item(3, 2500, "Техническая поддержка", unit="мес.", tax=22))

out = sys.argv[1] if len(sys.argv) > 1 else "schet.pdf"
RussianInvoice(invoice).gen(out, generate_qr_code=True)
print("Готово:", out)
