# -*- coding: utf-8 -*-
# Copyright (c) 2018, Resilient Tech and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import json

import frappe
from bank_integration.bank_integration.api import get_bank_api


@frappe.whitelist()
def make_payment(docname, uid):

    payment_entry = frappe.get_doc("Payment Entry", docname)
    data = frappe._dict(
        {
            "from_account": payment_entry.paid_from,
            "to_account": payment_entry.party_bank_ac_no,
            "transfer_type": payment_entry.transfer_type,
            "amount": payment_entry.paid_amount,
            "payment_desc": payment_entry.payment_desc,
            "docname": docname,
        }
    )

    bi_name = frappe.db.get_value(
        "Bank Account", {"account": data.from_account}, "name"
    )
    if not frappe.db.exists("Bank Integration Settings", bi_name):
        frappe.throw(
            "No Bank Integration Settings found for bank account {}".format(
                data.from_account
            )
        )
    bi = frappe.get_doc("Bank Integration Settings", bi_name)

    if bi.disabled:
        frappe.throw(
            "Bank Integration Settings for bank account {} is disabled".format(
                data.from_account
            )
        )

    data.from_account = bi.bank_account_no

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
def make_bulk_payment(docname_list, uid):

    docname_list = json.loads(docname_list)
    data_converted_to_frappe_dict = []

    for docname in docname_list:
        payment_entry = frappe.get_doc("Payment Entry", docname)
        data = frappe._dict(
            {
                "from_account": payment_entry.paid_from,
                "to_account": payment_entry.party_bank_ac_no,
                "transfer_type": payment_entry.transfer_type,
                "amount": payment_entry.paid_amount,
                "payment_desc": payment_entry.payment_desc,
                "docname": docname,
                "doctype": "Payment Entry",
            }
        )
        data_converted_to_frappe_dict.append(data)

    bank_account_no = []
    for frappe_dict_data in data_converted_to_frappe_dict:
        bi_name = frappe.db.get_value(
            "Bank Account", {"account": frappe_dict_data.from_account}, "name"
        )
        if not frappe.db.exists("Bank Integration Settings", bi_name):
            frappe.throw(
                "No Bank Integration Settings found for bank account {}".format(
                    frappe_dict_data.from_account
                )
            )
        bi = frappe.get_doc("Bank Integration Settings", bi_name)

        if bi.disabled:
            frappe.throw(
                "Bank Integration Settings for bank account {} is disabled".format(
                    frappe_dict_data.from_account
                )
            )

        frappe_dict_data.from_account = bi.bank_account_no
        bank_account_no.append(bi.bank_account_no)

    if len(set(bank_account_no)) > 1:
        frappe.throw(
            "All payments should have same bank account for bulk payment processing"
        )

    bank = get_bank_api(
        bi.bank_name,
        bi.username,
        bi.get_password(),
        doctype="Payment Entry",
        uid=uid,
        bulk_payments=data_converted_to_frappe_dict,
    )


# validate or support multiple bi
