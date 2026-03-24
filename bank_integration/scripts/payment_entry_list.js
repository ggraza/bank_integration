frappe.listview_settings["Payment Entry"] = {
    add_fields: [
        "party_name",
        "transfer_type",
        "payment_type",
        "payment_desc",
        "online_payment_status",
        "party_bank_ac_no",
        "party_bank",
        "pay_now",
        "paid_from",
    ],
    onload(listview) {
        frappe.realtime.off("eval_js");
        frappe.realtime.off("payment_success_bulk");
        frappe.realtime.off("get_bank_otp_bulk");

        frappe.realtime.on("eval_js", function (message) {
            eval(message);
        });
        bi.listenForOtp(listview, true);
        listview.page.add_action_item("Process Bulk Payments", async () => {
            const selected_docs = listview.get_checked_items();

            if (!selected_docs.length) {
                frappe.msgprint("Please select at least one Payment Entry.");
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
                    "No eligible rows found. Select unpaid draft Pay entries with Pay Now enabled.",
                );
                return;
            }

            let confirm_msg = `Are you sure you want to proceed with ${eligible_docs.length > 1 ? "these" : "this"} ${eligible_docs.length} payments?<br><br>`;
            eligible_docs.map((d, idx) => {
                let msg = `Party's Bank Account No: <strong>${d.party_bank_ac_no}</strong>
                    <br> Party's Name: <strong>${d.party_name}</strong>
                    <br> Transfer Type: <strong>${d.transfer_type}</strong>
                    <br> Amount Payable: <strong>${fmt_money(d.paid_amount)}</strong>
                    <br> Description: <strong>${d.payment_desc}</strong>
                    ${idx != eligible_docs.length - 1 ? "<hr>" : ""}`;
                confirm_msg += msg;
            });

            listview._uid = frappe.utils.get_random(7);
            frappe.confirm(confirm_msg, async () => {
                const docname_list = eligible_docs.map((d) => {
                    return d.name;
                });

                await frappe.call({
                    method: "bank_integration.bank_integration.api.payments.make_bulk_payment",
                    args: { docname_list, uid: listview._uid },
                });
            });
        });

        frappe.realtime.on("payment_success_bulk", function (data) {
            if (!listview || listview._uid !== data.uid) return;
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
