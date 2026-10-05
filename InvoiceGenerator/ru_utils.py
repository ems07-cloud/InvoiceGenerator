# -*- coding: utf-8 -*-
"""
Российская специфика счёта: сумма прописью, проверка реквизитов по контрольным цифрам,
строка платёжного QR-кода по ГОСТ Р 56042-2014, форматирование сумм и дат.
"""
from decimal import Decimal, ROUND_HALF_UP

MONTHS_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
              "сентября", "октября", "ноября", "декабря"]

_ONES = {
    "m": ["", "один", "два", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять"],
    "f": ["", "одна", "две", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять"],
}
_TEENS = ["десять", "одиннадцать", "двенадцать", "тринадцать", "четырнадцать", "пятнадцать",
          "шестнадцать", "семнадцать", "восемнадцать", "девятнадцать"]
_TENS = ["", "", "двадцать", "тридцать", "сорок", "пятьдесят", "шестьдесят", "семьдесят",
         "восемьдесят", "девяносто"]
_HUNDREDS = ["", "сто", "двести", "триста", "четыреста", "пятьсот", "шестьсот", "семьсот",
             "восемьсот", "девятьсот"]
# (формы «1 / 2-4 / 5-20», род)
_SCALES = [
    (("", "", ""), "m"),
    (("тысяча", "тысячи", "тысяч"), "f"),
    (("миллион", "миллиона", "миллионов"), "m"),
    (("миллиард", "миллиарда", "миллиардов"), "m"),
    (("триллион", "триллиона", "триллионов"), "m"),
]


def plural(n, forms):
    """Форма слова для числа: plural(3, ("рубль", "рубля", "рублей")) → «рубля»."""
    n = abs(int(n)) % 100
    if 11 <= n <= 19:
        return forms[2]
    n %= 10
    if n == 1:
        return forms[0]
    if 2 <= n <= 4:
        return forms[1]
    return forms[2]


def _triple(n, gender):
    words = [_HUNDREDS[n // 100]]
    rest = n % 100
    if 10 <= rest <= 19:
        words.append(_TEENS[rest - 10])
    else:
        words += [_TENS[rest // 10], _ONES[gender][rest % 10]]
    return [w for w in words if w]


def number_in_words(n, gender="m"):
    """Целое число прописью: 21 → «двадцать один», 2 с gender="f" → «две»."""
    n = int(n)
    if n == 0:
        return "ноль"
    if n < 0:
        return "минус " + number_in_words(-n, gender)
    words = []
    for power in range(len(_SCALES) - 1, -1, -1):
        part = (n // 1000 ** power) % 1000
        if not part:
            continue
        forms, scale_gender = _SCALES[power]
        words += _triple(part, gender if power == 0 else scale_gender)
        if power:
            words.append(plural(part, forms))
    if n >= 1000 ** len(_SCALES):
        raise ValueError("слишком большое число")
    return " ".join(words)


def to_kopecks(amount):
    return int((Decimal(amount) * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def amount_in_words(amount):
    """Сумма прописью, как в счетах и договорах: «Сто двадцать три рубля 45 копеек»."""
    kop = to_kopecks(amount)
    if kop < 0:
        raise ValueError("сумма не может быть отрицательной")
    rub, kop = divmod(kop, 100)
    text = "%s %s %02d %s" % (number_in_words(rub), plural(rub, ("рубль", "рубля", "рублей")),
                              kop, plural(kop, ("копейка", "копейки", "копеек")))
    return text[0].upper() + text[1:]


def money(amount):
    """123456.5 → «123 456,50» (неразрывные пробелы между разрядами)."""
    kop = to_kopecks(amount)
    sign = "-" if kop < 0 else ""
    rub, kop = divmod(abs(kop), 100)
    return "%s%s,%02d" % (sign, "{:,}".format(rub).replace(",", " "), kop)


def quantity(value):
    """Количество без лишних нулей: 2 → «2», 1.5 → «1,5»."""
    d = Decimal(value).normalize()
    text = format(d, "f")
    return text.replace(".", ",")


def date_long(d):
    """7 октября 2026 г."""
    return "%d %s %d г." % (d.day, MONTHS_GEN[d.month - 1], d.year)


# ---------- проверка реквизитов ----------

def _digits(value, lengths):
    s = str(value or "").strip()
    return s if s.isdigit() and len(s) in lengths else None


def _inn_check(digits, weights):
    return sum(int(d) * w for d, w in zip(digits, weights)) % 11 % 10


def check_inn(inn):
    """ИНН организации (10 цифр) или ИП/физлица (12 цифр) с проверкой контрольных цифр."""
    s = _digits(inn, (10, 12))
    if not s:
        return False
    if len(s) == 10:
        return _inn_check(s, (2, 4, 10, 3, 5, 9, 4, 6, 8)) == int(s[9])
    return (_inn_check(s, (7, 2, 4, 10, 3, 5, 9, 4, 6, 8)) == int(s[10])
            and _inn_check(s, (3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8)) == int(s[11]))


def check_kpp(kpp):
    s = str(kpp or "").strip()
    return len(s) == 9 and s[:4].isdigit() and s[4:6].isalnum() and s[6:].isdigit()


def check_bik(bik):
    s = _digits(bik, (9,))
    return bool(s) and s.startswith("04")


_ACCOUNT_WEIGHTS = (7, 1, 3) * 8


def _account_key_ok(prefix3, account):
    total = sum(int(d) * w for d, w in zip(prefix3 + account, _ACCOUNT_WEIGHTS))
    return total % 10 == 0


def check_account(account, bik):
    """Расчётный счёт: 20 цифр, контрольный ключ считается вместе с последними цифрами БИК."""
    a, b = _digits(account, (20,)), _digits(bik, (9,))
    return bool(a and b) and _account_key_ok(b[-3:], a)


def check_corr_account(corr, bik):
    """Корреспондентский счёт: начинается на 301, ключ считается с «0» и цифрами 5–6 БИК."""
    a, b = _digits(corr, (20,)), _digits(bik, (9,))
    return bool(a and b) and a.startswith("301") and _account_key_ok("0" + b[4:6], a)


def requisites_errors(party, need_bank=True):
    """Список понятных ошибок в реквизитах стороны счёта (пустой — всё в порядке)."""
    errors = []
    who = party.summary
    if not check_inn(party.inn):
        errors.append("%s: ИНН %r не проходит проверку контрольных цифр" % (who, party.inn))
    if party.kpp and not check_kpp(party.kpp):
        errors.append("%s: неверный КПП %r" % (who, party.kpp))
    if len(str(party.inn or "")) == 10 and not party.kpp:
        errors.append("%s: у организации должен быть КПП" % who)
    if need_bank:
        if not check_bik(party.bik):
            errors.append("%s: неверный БИК %r" % (who, party.bik))
        elif not check_account(party.bank_account, party.bik):
            errors.append("%s: расчётный счёт %r не сходится с БИК — проверьте цифры" % (who, party.bank_account))
        if party.corr_account and check_bik(party.bik) and not check_corr_account(party.corr_account, party.bik):
            errors.append("%s: корр. счёт %r не сходится с БИК" % (who, party.corr_account))
    return errors


# ---------- QR-код для оплаты по ГОСТ Р 56042-2014 ----------

def _qr_value(value):
    # «|» — разделитель полей, внутри значений его быть не должно
    return " ".join(str(value).replace("|", "/").split())


def gost_qr_payload(provider, amount, purpose):
    """Строка «ST00012|Name=…|PersonalAcc=…|…|Sum=…» — её понимают приложения российских банков."""
    fields = [
        ("Name", provider.summary),
        ("PersonalAcc", provider.bank_account),
        ("BankName", provider.bank_name),
        ("BIC", provider.bik),
        ("CorrespAcc", provider.corr_account or "0"),
        ("PayeeINN", provider.inn),
        ("KPP", provider.kpp),
        ("Sum", to_kopecks(amount)),
        ("Purpose", purpose),
    ]
    return "ST00012|" + "|".join("%s=%s" % (k, _qr_value(v)) for k, v in fields if v not in (None, ""))
