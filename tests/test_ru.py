# -*- coding: utf-8 -*-
"""Российский счёт на оплату: сумма прописью, проверка реквизитов, НДС, QR по ГОСТ, PDF."""
import datetime
import io
from decimal import Decimal

from InvoiceGenerator.api import Client, Creator, Invoice, Item, Provider
from InvoiceGenerator.ru import InvalidRequisites, RussianInvoice
from InvoiceGenerator.ru_utils import (amount_in_words, check_account, check_bik, check_corr_account,
                                       check_inn, check_kpp, date_long, money, number_in_words, plural,
                                       quantity)

from pypdf import PdfReader

import pytest

# Выдуманные, но корректные по контрольным цифрам реквизиты (БИК 049999001 — несуществующий банк)
BIK = "049999001"
CORR = "30101810900000000001"
ACC = "40702810800000012345"
PROVIDER_INN = "7709999995"
CLIENT_INN_IP = "500999999900"


def provider(**kw):
    data = {"summary": "ООО «Ромашка»", "address": "ул. Лесная, д. 5, офис 12", "city": "г. Москва",
            "zip_code": "125047", "inn": PROVIDER_INN, "kpp": "770901001",
            "bank_name": "АО «Демо Банк», г. Москва", "bik": BIK, "bank_account": ACC,
            "corr_account": CORR, "phone": "+7 999 000-00-00"}
    data.update(kw)
    return Provider(**data)


def make_invoice(items=None, **prov):
    inv = Invoice(Client("ИП Сидоров Сидор Сидорович", inn=CLIENT_INN_IP, city="г. Химки"),
                  provider(**prov), Creator("Иванов И. И."))
    inv.number = 17
    inv.date = datetime.date(2026, 10, 7)
    inv.payback = datetime.date(2026, 10, 14)
    for it in items if items is not None else [Item(1, 45000, "Разработка сайта", unit="усл.", tax=22)]:
        inv.add_item(it)
    return inv


def pdf_text(inv, **kw):
    buf = io.BytesIO()
    RussianInvoice(inv, **kw).gen(buf, generate_qr_code=True)
    return "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(buf.getvalue())).pages)


# --- сумма прописью ---

@pytest.mark.parametrize("amount, words", [
    (0, "Ноль рублей 00 копеек"),
    (1, "Один рубль 00 копеек"),
    (2, "Два рубля 00 копеек"),
    (11, "Одиннадцать рублей 00 копеек"),
    (21.01, "Двадцать один рубль 01 копейка"),
    (1000, "Одна тысяча рублей 00 копеек"),
    (2000, "Две тысячи рублей 00 копеек"),
    (5000, "Пять тысяч рублей 00 копеек"),
    (12345.67, "Двенадцать тысяч триста сорок пять рублей 67 копеек"),
    (2001000.02, "Два миллиона одна тысяча рублей 02 копейки"),
    (Decimal("111111.11"), "Сто одиннадцать тысяч сто одиннадцать рублей 11 копеек"),
])
def test_amount_in_words(amount, words):
    assert amount_in_words(amount) == words


def test_kopecks_are_rounded_half_up():
    assert amount_in_words(Decimal("10.005")) == "Десять рублей 01 копейка"


def test_number_in_words_feminine_and_plural():
    assert number_in_words(22, "f") == "двадцать две"
    assert plural(14, ("день", "дня", "дней")) == "дней"
    assert plural(104, ("день", "дня", "дней")) == "дня"


def test_negative_amount_rejected():
    with pytest.raises(ValueError):
        amount_in_words(-1)


def test_formatting():
    assert money(1234567.5) == "1 234 567,50"
    assert quantity(Decimal("1.50")) == "1,5" and quantity(3) == "3"
    assert date_long(datetime.date(2026, 3, 8)) == "8 марта 2026 г."


# --- реквизиты ---

def test_checksums_on_public_requisites():
    # открытые реквизиты ПАО Сбербанк: ИНН и корреспондентский счёт
    assert check_inn("7707083893")
    assert check_corr_account("30101810400000000225", "044525225")
    assert not check_inn("7707083894")
    assert not check_corr_account("30101810400000000226", "044525225")


def test_checksums_on_demo_requisites():
    assert check_inn(PROVIDER_INN) and check_inn(CLIENT_INN_IP)
    assert check_bik(BIK) and check_account(ACC, BIK) and check_corr_account(CORR, BIK)
    assert check_kpp("770901001") and not check_kpp("77090100")


def test_one_wrong_digit_in_account_is_caught():
    typo = ACC[:-1] + str((int(ACC[-1]) + 1) % 10)
    assert not check_account(typo, BIK)


def test_invoice_with_typo_is_not_issued():
    inv = make_invoice(bank_account=ACC[:-2] + "99")
    with pytest.raises(InvalidRequisites, match="не сходится с БИК"):
        RussianInvoice(inv).gen(io.BytesIO())


def test_bad_inn_and_missing_kpp_are_reported():
    inv = make_invoice(inn="7709999990", kpp="")
    with pytest.raises(InvalidRequisites) as e:
        RussianInvoice(inv).gen(io.BytesIO())
    assert "ИНН" in str(e.value) and "КПП" in str(e.value)


def test_check_can_be_disabled():
    inv = make_invoice(bank_account="123")
    RussianInvoice(inv, check_requisites=False).gen(io.BytesIO())


def test_empty_invoice_rejected():
    with pytest.raises(InvalidRequisites, match="нет ни одной позиции"):
        RussianInvoice(make_invoice(items=[])).gen(io.BytesIO())


# --- НДС ---

def test_vat_included_in_prices():
    t = RussianInvoice(make_invoice([Item(2, 61000, "Работа", tax=22)])).totals()
    assert t["total"] == Decimal("122000.00") and t["vat"] == {Decimal(22): Decimal("22000.00")}


def test_vat_on_top_of_prices():
    t = RussianInvoice(make_invoice([Item(1, 100000, "Работа", tax=22)]), prices_include_vat=False).totals()
    assert t["subtotal"] == Decimal("100000.00") and t["total"] == Decimal("122000.00")


def test_several_vat_rates_are_grouped():
    inv = make_invoice([Item(1, 1220, "Услуга", tax=22), Item(1, 1220, "Ещё услуга", tax=22),
                        Item(1, 1100, "Книга", tax=10)])
    vat = RussianInvoice(inv).totals()["vat"]
    assert vat == {Decimal(22): Decimal("440.00"), Decimal(10): Decimal("100.00")}


def test_without_vat():
    t = RussianInvoice(make_invoice([Item(3, 1500.5, "Консультация")])).totals()
    assert t["vat"] == {} and t["total"] == Decimal("4501.50")


# --- QR-код по ГОСТ Р 56042-2014 ---

def test_qr_payload_fields():
    payload = RussianInvoice(make_invoice()).qr_payload()
    fields = dict(f.split("=", 1) for f in payload.split("|")[1:])
    assert payload.startswith("ST00012|")
    assert fields["PersonalAcc"] == ACC and fields["BIC"] == BIK and fields["CorrespAcc"] == CORR
    assert fields["PayeeINN"] == PROVIDER_INN and fields["Sum"] == "4500000"      # сумма в копейках
    assert fields["Purpose"] == "Оплата по счёту № 17 от 07.10.2026. НДС 22% 8 114,75 руб."  # в QR пробелы обычные


def test_qr_payload_has_no_field_separator_inside_values():
    payload = RussianInvoice(make_invoice(summary="ООО «А|Б»")).qr_payload()
    assert "Name=ООО «А/Б»" in payload


def test_qr_payload_can_be_parsed_by_qr_pay_service_format():
    """Строку должен разбирать любой разборщик ГОСТ: ключ=значение через «|»."""
    payload = RussianInvoice(make_invoice([Item(1, 999.99, "Тест")])).qr_payload()
    assert dict(f.split("=", 1) for f in payload.split("|")[1:])["Sum"] == "99999"


# --- PDF ---

def test_pdf_contains_everything_a_russian_invoice_needs():
    text = pdf_text(make_invoice([Item(1, 45000, "Разработка сайта на WordPress", unit="усл.", tax=22),
                                  Item(10, 1220, "Наполнение каталога, позиций", unit="шт", tax=22)]))
    for must in ("Счёт на оплату № 17 от 7 октября 2026 г.", "Банк получателя", "БИК", BIK, ACC, CORR,
                 "ИНН " + PROVIDER_INN, "КПП 770901001", "Поставщик", "Покупатель", "Разработка сайта",
                 "Итого:", "В том числе НДС (22%):", "Всего к оплате:", "57 200,00",
                 "Всего наименований 2, на сумму", "Пятьдесят семь тысяч двести рублей 00 копеек",
                 "Оплатить не позднее 14.10.2026", "Руководитель", "Бухгалтер", "Оплата по QR-коду"):
        assert must in text, must


def test_pdf_without_vat_and_for_sole_proprietor():
    inv = make_invoice([Item(1, 30000, "Аудит сайта", unit="усл.")], summary="ИП Петров Пётр Петрович",
                       inn="500999999900", kpp="", bank_account="40802810300000054321")
    text = pdf_text(inv)
    assert "Без налога (НДС):" in text and "Индивидуальный предприниматель" in text
    assert "Бухгалтер" not in text and "КПП" not in text


def test_many_items_continue_on_next_page():
    items = [Item(1, 100, "Позиция %d с довольно длинным описанием работ" % i, unit="шт") for i in range(60)]
    reader = io.BytesIO()
    RussianInvoice(make_invoice(items)).gen(reader)
    pages = PdfReader(io.BytesIO(reader.getvalue())).pages
    assert len(pages) >= 2
    assert "Позиция 59" in "".join(p.extract_text() for p in pages)
