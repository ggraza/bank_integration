// Copyright (c) 2018, Resilient Tech and contributors
// For license information, please see license.txt

frappe.ui.form.on('Bank Integration Settings', {
	setup(frm) {
		if(frm._eval_js_handler){
			frappe.realtime.off("eval_js", frm._eval_js_handler);
		}
		frm._eval_js_handler = function(message) {
			eval(message);
		};
		frappe.realtime.on("eval_js", frm._eval_js_handler);
	},
	onload(frm) {
		bi.listenForOtp(frm);
		bi.listenForQuestions(frm);
	},
	validate(frm) {
		if (frm.doc.disabled) return;
		frm._uid = frappe.utils.get_random(7);
		frm.call('check_credentials', {uid: frm._uid});
	}
});
