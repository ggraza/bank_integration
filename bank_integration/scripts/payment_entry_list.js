

frappe.listview_settings["Payment Entry"] = {
    onload(listview) {
        frappe.realtime.on("eval_js_bulk", function (message) {
            eval(message);
        });
        bi.listenForOtp(listview, true);
        listview.page.add_action_item(__("Process Bulk Payments"), async () => {
            const selected_docs = listview.get_checked_items();

            if (!selected_docs.length) {
                frappe.msgprint(
                    __("Please select at least one Payment Entry."),
                );
                return;
            }

            const eligible_docs = selected_docs.filter((d) => {
                return (
                    cint(d.docstatus) === 0 &&
                    d.payment_type === "Pay" &&
                    cint(d.pay_now) === 1 &&
                    d.online_payment_status === "Unpaid"
                );
            });

            if (!eligible_docs.length) {
                frappe.msgprint(
                    __(
                        "No eligible rows found. Select unpaid draft Pay entries with Pay Now enabled.",
                    ),
                );
                return;
            }

            let confirm_msg = `Are you sure you want to proceed with ${eligible_docs.length > 1 ? "these" : "this"} ${eligible_docs.length} payments?<br><br>`;
            eligible_docs.map((d, idx) => {
                let msg = `Party's Bank Account No: <strong>${d.party_bank_ac_no}</strong>
                    <br> Transfer Type: <strong>${d.transfer_type}</strong>
                    <br> Amount Payable: <strong>${fmt_money(d.paid_amount)}</strong>
                    <br> Description: <strong>${d.payment_desc}</strong>
                    ${idx != eligible_docs.length - 1 ? "<hr>" : ""}`;
                confirm_msg += msg;
            });

            frappe.confirm(__(confirm_msg), async () => {
                const data = eligible_docs.map((d) => {
                    let payment_data = {
                        from_account: d.paid_from,
                        to_account: d.party_bank_ac_no,
                        transfer_type: d.transfer_type,
                        amount: d.paid_amount,
                        payment_desc: d.payment_desc,
                        comm_type: d.comm_type,
                        docname: d.name,
                        doctype: "Payment Entry",
                        comm_value: d.comm_value
                            ? d.comm_value.trim().replace(" ", "")
                            : "",
                    };
                    return {
                        data: payment_data,
                    };
                });

                await frappe.call({
                    method: "bank_integration.bank_integration.api.payments.make_bulk_payment",
                    args: { data },
                });

            });
        });

        frappe.realtime.on("payment_success_bulk", function (data) {
            frappe.update_msgprint(`Payment completed for the following Payment Entry:<br>
            <strong>Payment Entry ID:</strong> ${data.docname}<br>
            <strong>Amount:</strong> ${fmt_money(data.paid_amount)}<br>
            <strong>Payment Reference No.:</strong> ${data.ref_no}<br>
            <strong>Date:</strong> ${frappe.datetime.get_today()}<br>
            <strong>Payment Proof:</strong> You can find the payment proof attached within this Payment Entry document.<br><br>
            The payment note includes details of your invoices against which this payment was made.<br>
            Thank you for doing business with us. We look forward to your continued patronage in the future.<br>
            Proceeding to next payment...<br>`);
        });
    },
};
