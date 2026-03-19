# -*- coding: utf-8 -*-
# Copyright (c) 2018, Resilient Tech and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import json

import frappe
from bank_integration.bank_integration.api import get_bank_api

@frappe.whitelist()
def make_payment(docname, uid, data):
    data = frappe._dict(json.loads(data))

    bi_name = frappe.db.get_value('Bank Account', {'account': data.from_account}, 'name')
    bi = frappe.get_doc('Bank Integration Settings', bi_name)
    data.from_account = bi.bank_account_no

    bank = get_bank_api(bi.bank_name, bi.username, bi.get_password(), doctype="Payment Entry", docname=docname,
        uid=uid, data=data)

@frappe.whitelist()
def make_bulk_payment(data):
    bulk_data=json.loads(data)
    data_converted_to_frappe_dict=[]
    for d in bulk_data:
        frappe_dict_d = frappe._dict(d)
        frappe_dict_data=frappe._dict(frappe_dict_d.data)

        bi_name = frappe.db.get_value('Bank Account', {'account': frappe_dict_data.from_account}, 'name')
        bi = frappe.get_doc('Bank Integration Settings', bi_name)
        frappe_dict_data.from_account = bi.bank_account_no
        data_converted_to_frappe_dict.append(frappe_dict_data)
    # not using changed data
    bank = get_bank_api(bi.bank_name, bi.username, bi.get_password(), doctype="Payment Entry", 
         bulk_payments=data_converted_to_frappe_dict)