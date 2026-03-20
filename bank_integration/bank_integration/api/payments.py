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

    bi_name = frappe.db.get_value(
        "Bank Account", {"account": data.from_account}, "name"
    )
    bi = frappe.get_doc("Bank Integration Settings", bi_name)
    data.from_account = bi.bank_account_no
    data.docname = docname

    bank = get_bank_api(
        bi.bank_name,
        bi.username,
        bi.get_password(),
        doctype="Payment Entry",
        docname=docname,
        uid=uid,
        data=data,
    )


# bulk payments will use only one bank integration settings containing id, password and account no.
# therefore all the payments will be made using those settings
@frappe.whitelist()
def make_bulk_payment(data, uid):
    bulk_data = json.loads(data)
    data_converted_to_frappe_dict = []
    for d in bulk_data:
        frappe_dict_data = frappe._dict(d["data"])

        bi_name = frappe.db.get_value(
            "Bank Account", {"account": frappe_dict_data.from_account}, "name"
        )
        bi = frappe.get_doc("Bank Integration Settings", bi_name)
        frappe_dict_data.from_account = bi.bank_account_no
        data_converted_to_frappe_dict.append(frappe_dict_data)

    bank = get_bank_api(
        bi.bank_name,
        bi.username,
        bi.get_password(),
        doctype="Payment Entry",
        uid=uid,
        bulk_payments=data_converted_to_frappe_dict,
    )
