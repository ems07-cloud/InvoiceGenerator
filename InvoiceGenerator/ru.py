# -*- coding: utf-8 -*-
"""
Российский «Счёт на оплату» в привычном виде (как в 1С): банковские реквизиты получателя
сверху, поставщик и покупатель с ИНН/КПП, таблица работ и услуг, НДС или «Без НДС»,
сумма прописью, подписи и QR-код для оплаты из приложения банка (ГОСТ Р 56042-2014).

Пример::

    from InvoiceGenerator.api import Client, Creator, Invoice, Item, Provider
    from InvoiceGenerator.ru import RussianInvoice

    provider = Provider("ООО «Ромашка»", address="г. Москва, ул. Лесная, д. 5", inn="...", kpp="...",
                        bank_name="АО «Банк»", bik="...", bank_account="...", corr_account="...")
    invoice = Invoice(Client("ИП Иванов И. И.", inn="..."), provider, Creator("Петров П. П."))
    invoice.number = 17
    invoice.date = datetime.date(2026, 10, 7)
    invoice.add_item(Item(1, 45000, description="Разработка сайта", unit="усл.", tax=22))
    RussianInvoice(invoice).gen("schet.pdf", generate_qr_code=True)

Цены по умолчанию считаются уже включающими НДС («В том числе НДС»), как принято в
российских счетах. Если цены указаны без налога — ``RussianInvoice(invoice, prices_include_vat=False)``.
Счёт без НДС (УСН, самозанятые) — просто не задавайте ``tax`` у позиций.
"""
import io
from collections import OrderedDict
from decimal import Decimal

from InvoiceGenerator.api import Invoice
from InvoiceGenerator.conf import FONT_BOLD_PATH, FONT_PATH
from InvoiceGenerator.ru_utils import (amount_in_words, date_long, gost_qr_payload, money, quantity,
                                       requisites_errors)

import qrcode

from reportlab.lib.colors import HexColor, black
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Paragraph

__all__ = ["RussianInvoice", "InvalidRequisites"]

FONT, FONT_BOLD = "DejaVu", "DejaVu-Bold"
TWO = Decimal("0.01")


class InvalidRequisites(ValueError):
    """Ошибка в реквизитах: счёт с такими данными не оплатят или деньги уйдут не туда."""


def _register_fonts():
    if FONT not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(FONT, FONT_PATH))
        pdfmetrics.registerFont(TTFont(FONT_BOLD, FONT_BOLD_PATH))
        # без семейства тег <b> в абзацах молча остаётся обычным шрифтом
        pdfmetrics.registerFontFamily(FONT, normal=FONT, bold=FONT_BOLD, italic=FONT, boldItalic=FONT_BOLD)


def _escape(text):
    return str(text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class RussianInvoice(object):
    """
    Генератор PDF «Счёт на оплату».

    :param invoice: счёт из InvoiceGenerator.api (позиции, номер, даты, стороны)
    :param prices_include_vat: цены позиций уже с НДС (по умолчанию) или без него
    :param check_requisites: проверять ИНН, БИК и счета по контрольным цифрам перед выпуском
    """

    LEFT = 15 * mm
    WIDTH = A4[0] - 30 * mm

    def __init__(self, invoice, prices_include_vat=True, check_requisites=True):
        assert isinstance(invoice, Invoice), "invoice is not instance of Invoice"
        self.invoice = invoice
        self.prices_include_vat = prices_include_vat
        self.check_requisites = check_requisites

    # ---------- расчёты ----------

    def rows(self):
        """Строки таблицы: (№, наименование, кол-во, ед., цена, сумма)."""
        out = []
        for i, item in enumerate(self.invoice.items, 1):
            price = Decimal(item.price).quantize(TWO)
            out.append((i, item.description, item.count, item.unit, price, (price * item.count).quantize(TWO)))
        return out

    def totals(self):
        """
        Итоги: сумма по строкам, НДС по ставкам и сумма к оплате.

        :return: dict(subtotal, vat=OrderedDict(ставка → сумма налога), total)
        """
        subtotal = sum((r[5] for r in self.rows()), Decimal(0))
        vat = OrderedDict()
        for item in self.invoice.items:
            rate = Decimal(item.tax or 0)
            if not rate:
                continue
            line = (Decimal(item.price).quantize(TWO) * item.count).quantize(TWO)
            tax = line * rate / (100 + rate) if self.prices_include_vat else line * rate / 100
            vat[rate] = vat.get(rate, Decimal(0)) + tax
        vat = OrderedDict((k, v.quantize(TWO)) for k, v in vat.items())
        total = subtotal if self.prices_include_vat else subtotal + sum(vat.values(), Decimal(0))
        return {"subtotal": subtotal, "vat": vat, "total": total}

    def purpose(self):
        inv = self.invoice
        vat = self.totals()["vat"]
        if vat:
            tax = ", ".join("НДС %s%% %s руб." % (quantity(rate), money(v)) for rate, v in vat.items())
        else:
            tax = "Без НДС"
        return "Оплата по счёту № %s от %s. %s" % (inv.number, inv.date.strftime("%d.%m.%Y"), tax)

    def qr_payload(self):
        return gost_qr_payload(self.invoice.provider, self.totals()["total"], self.purpose())

    def validate(self):
        inv = self.invoice
        errors = requisites_errors(inv.provider, need_bank=True)
        if inv.client.inn:
            errors += requisites_errors(inv.client, need_bank=False)
        if not inv.items:
            errors.append("В счёте нет ни одной позиции")
        if not inv.number or not inv.date:
            errors.append("Не указаны номер или дата счёта")
        if errors:
            raise InvalidRequisites("; ".join(errors))

    # ---------- вывод ----------

    def gen(self, filename, generate_qr_code=False):
        """
        Создаёт PDF.

        :param filename: путь к файлу или файловый объект
        :param generate_qr_code: добавить QR-код для оплаты из приложения банка
        """
        if self.check_requisites:
            self.validate()
        _register_fonts()
        self.pdf = Canvas(filename, pagesize=A4)
        inv = self.invoice
        self.pdf.setAuthor(inv.provider.summary)
        self.pdf.setTitle("Счёт на оплату № %s" % inv.number)
        self.pdf.setSubject("Счёт на оплату")
        self.pdf.setCreator("InvoiceGenerator")
        y = A4[1] - 15 * mm
        y = self._bank_block(y)
        y = self._title(y - 8 * mm)
        y = self._parties(y - 4 * mm)
        y = self._items(y - 5 * mm)
        y = self._totals(y)
        y = self._summary(y - 3 * mm)
        self._signatures(y, generate_qr_code)
        self.pdf.showPage()
        self.pdf.save()

    def _text(self, x, y, text, size=9, bold=False, right=False):
        self.pdf.setFont(FONT_BOLD if bold else FONT, size)
        (self.pdf.drawRightString if right else self.pdf.drawString)(x, y, str(text))

    def _para(self, html, width, size=9, leading=None, bold=False):
        style = ParagraphStyle("p", fontName=FONT_BOLD if bold else FONT, fontSize=size,
                               leading=leading or size * 1.25)
        p = Paragraph(html, style)
        _, h = p.wrap(width, 1000)
        return p, h

    def _bank_block(self, top):
        """Таблица реквизитов получателя, как в платёжке."""
        prov = self.invoice.provider
        x0, w = self.LEFT, self.WIDTH
        c1, c2 = x0 + w * 0.58, x0 + w * 0.68           # граница «банк | БИК», «БИК | значение»
        h1, h2 = 13 * mm, 14 * mm
        y1, y2 = top - h1, top - h1 - h2
        pdf = self.pdf
        pdf.setLineWidth(0.6)
        pdf.rect(x0, y2, w, h1 + h2)
        pdf.line(c1, y2, c1, top)
        pdf.line(c2, y2, c2, top)
        pdf.line(x0, y1, x0 + w, y1)
        pdf.line(c1, top - 6 * mm, x0 + w, top - 6 * mm)
        inn_split = x0 + (c1 - x0) / 2
        pdf.line(x0, y1 - 5 * mm, c1, y1 - 5 * mm)
        pdf.line(inn_split, y1, inn_split, y1 - 5 * mm)

        p, ph = self._para(_escape(prov.bank_name), c1 - x0 - 4 * mm)
        p.drawOn(pdf, x0 + 2 * mm, top - 2 * mm - ph)
        self._text(x0 + 2 * mm, y1 + 1.5 * mm, "Банк получателя", 7)
        self._text(c1 + 2 * mm, top - 4.3 * mm, "БИК", 9)
        self._text(c2 + 2 * mm, top - 4.3 * mm, prov.bik, 9)
        self._text(c1 + 2 * mm, top - 10 * mm, "Сч. №", 9)
        self._text(c2 + 2 * mm, top - 10 * mm, prov.corr_account, 9)
        self._text(x0 + 2 * mm, y1 - 3.6 * mm, "ИНН %s" % prov.inn, 9)
        self._text(inn_split + 2 * mm, y1 - 3.6 * mm, ("КПП %s" % prov.kpp) if prov.kpp else "", 9)
        self._text(c1 + 2 * mm, y1 - 3.6 * mm, "Сч. №", 9)
        self._text(c2 + 2 * mm, y1 - 3.6 * mm, prov.bank_account, 9)
        p, ph = self._para(_escape(prov.summary), c1 - x0 - 4 * mm)
        p.drawOn(pdf, x0 + 2 * mm, y1 - 5.5 * mm - ph)
        self._text(x0 + 2 * mm, y2 + 1.5 * mm, "Получатель", 7)
        return y2

    def _title(self, y):
        inv = self.invoice
        title = "Счёт на оплату № %s от %s" % (inv.number, date_long(inv.date))
        self._text(self.LEFT, y, title, 14, bold=True)
        self.pdf.setLineWidth(1.6)
        self.pdf.line(self.LEFT, y - 3 * mm, self.LEFT + self.WIDTH, y - 3 * mm)
        return y - 3 * mm

    @staticmethod
    def _party_line(party):
        parts = [party.summary]
        if party.inn:
            parts.append("ИНН %s" % party.inn)
        if party.kpp:
            parts.append("КПП %s" % party.kpp)
        address = ", ".join(x for x in (party.zip_code, party.city, party.address) if x)
        if address:
            parts.append(address)
        if party.phone:
            parts.append("тел.: %s" % party.phone)
        return ", ".join(parts)

    def _parties(self, y):
        inv = self.invoice
        label_w = 32 * mm
        rows = [("Поставщик<br/>(Исполнитель):", self._party_line(inv.provider)),
                ("Покупатель<br/>(Заказчик):", self._party_line(inv.client))]
        basis = getattr(inv, "basis", None)
        if basis:
            rows.append(("Основание:", basis))
        for label, text in rows:
            lp, lh = self._para(label, label_w - 2 * mm, 9)
            tp, th = self._para("<b>%s</b>" % _escape(text), self.WIDTH - label_w, 9)
            h = max(lh, th)
            y -= h + 2.5 * mm
            lp.drawOn(self.pdf, self.LEFT, y + h - lh)
            tp.drawOn(self.pdf, self.LEFT + label_w, y + h - th)
        return y

    COLS = (("№", 9 * mm), ("Товары (работы, услуги)", None), ("Кол-во", 17 * mm), ("Ед.", 13 * mm),
            ("Цена", 25 * mm), ("Сумма", 27 * mm))

    def _col_x(self):
        fixed = sum(w for _, w in self.COLS if w)
        widths = [w or (self.WIDTH - fixed) for _, w in self.COLS]
        xs = [self.LEFT]
        for w in widths:
            xs.append(xs[-1] + w)
        return xs, widths

    def _items_header(self, y):
        xs, widths = self._col_x()
        h = 7 * mm
        pdf = self.pdf
        pdf.setLineWidth(1.2)
        pdf.rect(self.LEFT, y - h, self.WIDTH, h)
        pdf.setLineWidth(0.5)
        for i, (name, _) in enumerate(self.COLS):
            if i:
                pdf.line(xs[i], y - h, xs[i], y)
            self._text(xs[i] + widths[i] / 2 - pdf.stringWidth(name, FONT_BOLD, 9) / 2, y - 4.7 * mm,
                       name, 9, bold=True)
        return y - h

    def _items(self, y):
        xs, widths = self._col_x()
        pdf = self.pdf
        y = self._items_header(y)
        for n, desc, count, unit, price, total in self.rows():
            p, ph = self._para(_escape(desc), widths[1] - 3 * mm, 9)
            h = max(ph + 2.5 * mm, 6 * mm)
            if y - h < 45 * mm:                         # не влезает — переносим на следующую страницу
                pdf.showPage()
                y = self._items_header(A4[1] - 15 * mm)
            pdf.setLineWidth(0.5)
            pdf.rect(self.LEFT, y - h, self.WIDTH, h)
            for i in range(1, len(self.COLS)):
                pdf.line(xs[i], y - h, xs[i], y)
            base = y - 4.2 * mm
            self._text(xs[1] - 1.5 * mm, base, n, 9, right=True)
            p.drawOn(pdf, xs[1] + 1.5 * mm, y - 1.3 * mm - ph)
            self._text(xs[3] - 1.5 * mm, base, quantity(count), 9, right=True)
            self._text(xs[3] + 1.5 * mm, base, unit or "", 9)
            self._text(xs[5] - 1.5 * mm, base, money(price), 9, right=True)
            self._text(xs[6] - 1.5 * mm, base, money(total), 9, right=True)
            y -= h
        return y

    def _totals(self, y):
        t = self.totals()
        right = self.LEFT + self.WIDTH - 1.5 * mm
        label_x = right - 30 * mm
        lines = [("Итого:", money(t["subtotal"]))]
        if t["vat"]:
            prefix = "В том числе НДС" if self.prices_include_vat else "НДС"
            lines += [("%s (%s%%):" % (prefix, quantity(rate)), money(v)) for rate, v in t["vat"].items()]
        else:
            lines.append(("Без налога (НДС):", "—"))
        lines.append(("Всего к оплате:", money(t["total"])))
        for label, value in lines:
            y -= 5 * mm
            self._text(label_x, y, label, 9.5, bold=True, right=True)
            self._text(right, y, value, 9.5, bold=True, right=True)
        return y

    def _summary(self, y):
        t = self.totals()
        n = len(self.invoice.items)
        y -= 6 * mm
        self._text(self.LEFT, y, "Всего наименований %d, на сумму %s руб." % (n, money(t["total"])), 9)
        p, ph = self._para("<b>%s</b>" % amount_in_words(t["total"]), self.WIDTH, 10)
        y -= ph + 1.5 * mm
        p.drawOn(self.pdf, self.LEFT, y)
        if self.invoice.payback:
            y -= 6 * mm
            self._text(self.LEFT, y, "Оплатить не позднее %s." % self.invoice.payback.strftime("%d.%m.%Y"), 9)
        note = getattr(self.invoice.provider, "note", "")
        if note:
            p, ph = self._para(_escape(note), self.WIDTH, 8, leading=10)
            y -= ph + 3 * mm
            p.drawOn(self.pdf, self.LEFT, y)
        self.pdf.setLineWidth(1.6)
        self.pdf.line(self.LEFT, y - 3 * mm, self.LEFT + self.WIDTH, y - 3 * mm)
        return y - 3 * mm

    QR_SIZE = 34 * mm

    def _signatures(self, top, generate_qr_code):
        """Подписи и QR-код под итоговой чертой (top — её высота на странице)."""
        inv = self.invoice
        if top < self.QR_SIZE + 20 * mm:                # подписи и QR не влезают — на новую страницу
            self.pdf.showPage()
            top = A4[1] - 15 * mm
        director = getattr(inv, "director", None) or inv.creator.name
        accountant = getattr(inv, "accountant", None) or director
        is_ip = len(str(inv.provider.inn or "")) == 12
        rows = [("Индивидуальный предприниматель" if is_ip else "Руководитель", director)]
        if not is_ip:
            rows.append(("Бухгалтер", accountant))
        # подпись начинается после самой длинной надписи, чтобы черта не наезжала на текст
        label_w = max(self.pdf.stringWidth(title, FONT_BOLD, 9) for title, _ in rows)
        line_from = self.LEFT + label_w + 4 * mm
        y = top - 6 * mm
        for title, name in rows:
            y -= 9 * mm
            self._text(self.LEFT, y, title, 9, bold=True)
            self.pdf.setLineWidth(0.5)
            self.pdf.line(line_from, y - 1, line_from + 35 * mm, y - 1)
            self._text(line_from + 38 * mm, y, name, 9)
        if generate_qr_code:
            self._qr(top)

    def _qr(self, top):
        size = self.QR_SIZE
        x = self.LEFT + self.WIDTH - size
        y = top - 4 * mm - size
        img = qrcode.make(self.qr_payload(), border=1, error_correction=qrcode.constants.ERROR_CORRECT_M)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        self.pdf.drawImage(ImageReader(buf), x, y, size, size)
        self.pdf.setFillColor(HexColor("#555555"))
        self._text(x + size / 2 - self.pdf.stringWidth("Оплата по QR-коду", FONT, 7.5) / 2, y - 3.5 * mm,
                   "Оплата по QR-коду", 7.5)
        self.pdf.setFillColor(black)
