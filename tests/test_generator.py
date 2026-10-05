# -*- coding: utf-8 -*-
import os
import unittest
from tempfile import TemporaryDirectory

from InvoiceGenerator.api import Client, Creator, Invoice, Item, Provider
from InvoiceGenerator.generator import Generator
from InvoiceGenerator.pdf import SimpleInvoice


class TestGenerator(unittest.TestCase):

    def test_assertation(self):
        self.assertRaises(AssertionError, Generator, object)
        generator = Generator(self._build_invoice())

        self.assertRaises(AssertionError, generator.gen, '/black/hole', object)

    def test_gen(self):
        # NamedTemporaryFile нельзя открыть второй раз на Windows — пишем во временную папку
        with TemporaryDirectory() as tmp:
            Generator(self._build_invoice()).gen(os.path.join(tmp, "invoice.pdf"), SimpleInvoice)

    def _build_invoice(self):
        invoice = Invoice(Client('John'), Provider('Doe'), Creator('John Doe'))
        invoice.add_item(Item(42, 666))
        return invoice
