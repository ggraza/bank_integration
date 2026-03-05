# -*- coding: utf-8 -*-
# Copyright (c) 2018, Resilient Tech and contributors
# For license information, please see license.txt

import time

import frappe
import hashlib
from frappe.utils import getdate, today, add_months, add_days, flt
from frappe.utils.file_manager import save_file

from bank_integration.bank_integration.api.bank_api import BankAPI, AnyEC

# Selenium imports
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.common.exceptions import (
    NoAlertPresentException,
    NoSuchElementException,
    TimeoutException,
)
from selenium.webdriver.common.keys import Keys


class HDFCBankAPI(BankAPI):
    def init(self):
        self.bank_name = "HDFC Bank"

    def login(self):
        self.show_msg("Attempting login...")
        self.setup_browser()
        self.br.get("https://netbanking.hdfcbank.com/netbanking/")

        self.switch_to_frame("login_page")
        cust_id = self.get_element("fldLoginUserId")
        cust_id.send_keys(self.username, Keys.ENTER)

        # After submitting the customer ID, HDFC removes all iframes and renders
        # the password screen directly in the main document. Switch back out.
        self.br.switch_to.default_content()
        pass_input = self.get_element("password", "id")
        # try:
        #     secure_access_cb = self.get_element(
        #         "chkrsastu", "id", timeout=2, throw=False
        #     )
        #     secure_access_cb.click()
        # except TimeoutException:
        #     pass

        # try:
        #     self.get_element("fldCaptcha", timeout=1, throw=False)
        # except TimeoutException:
        #     pass
        # else:
        #     self.throw(
        #         "HDFC Netbanking is asking for a CAPTCHA, which we don't currently support. Exiting."
        #     )

        # Inject a MutationObserver BEFORE pressing Enter so that any
        # element appearing transiently during Angular's page transition
        # (e.g. OTP screen visible for < 500ms) is still recorded even
        # if Selenium's 500ms poll cycle misses it entirely.
        # Watches both DOM additions AND style/class attribute changes so
        # it only records an element when it is actually visible on screen.
        self.br.execute_script("""
            window._hdfcSeenIds = new Set();
            function checkVisible(id) {
                var el = document.getElementById(id);
                if (el) {
                    var s = window.getComputedStyle(el);
                    if (s.display !== 'none' && s.visibility !== 'hidden' && s.opacity !== '0') {
                        window._hdfcSeenIds.add(id);
                    }
                }
            }
            var obs = new MutationObserver(function() {
                ['mfa-get-otp-btn', 'proceedBtn'].forEach(checkVisible);
            });
            obs.observe(document.documentElement, {
                childList: true,
                subtree: true,
                attributes: true,
                attributeFilter: ['style', 'class', 'hidden']
            });
            window._hdfcObserver = obs;
        """)

        pass_input.send_keys(self.password, Keys.ENTER)

        self.br.switch_to.default_content()
        self._handle_post_login_state()

    def _handle_post_login_state(self):
        """
        After password submission, HDFC can land on different screens:
          1. Invalid credentials error
          2. Password expired screen (fldOldPass)
          3. "Already logged in" dialog with a Proceed button (proceedBtn).
             This dialog can appear up to 2 times back-to-back.
          4. OTP screen (mfa-get-otp-btn)
          5. Security questions screen (fldAnswer)
          6. Angular dashboard (bb-retail-layout tag) — direct login success
        We loop up to 3 times so we can dismiss up to 2 proceed dialogs before
        reaching the final state.
        """
        # Stop the observer and retrieve which element ids were seen
        # transiently during Angular's page transition after password submit.
        seen_transiently = set(
            self.br.execute_script("""
            if (window._hdfcObserver) { window._hdfcObserver.disconnect(); }
            return window._hdfcSeenIds ? Array.from(window._hdfcSeenIds) : [];
        """)
            or []
        )

        for _ in range(3):
            self.wait_until(
                AnyEC(
                    EC.visibility_of_element_located(
                        (
                            By.XPATH,
                            "//td/span[text()[contains(.,'The Customer ID/IPIN (Password) is invalid.')]]",
                        )
                    ),
                    # EC.visibility_of_element_located((By.NAME, "fldOldPass")),
                    EC.visibility_of_element_located((By.ID, "proceedBtn")),
                    # visibility_of_element_located is correct here — only fires
                    # when truly visible. Transient appearances missed by the
                    # 500ms poll are caught by the MutationObserver above.
                    EC.visibility_of_element_located((By.ID, "mfa-get-otp-btn")),
                    # EC.visibility_of_element_located((By.NAME, "fldAnswer")),
                    EC.presence_of_element_located((By.TAG_NAME, "bb-retail-layout")),
                ),
                throw="ignore",
            )
            found = self.br._found_element

            if not found:
                # wait_until timed out — check if the observer recorded any
                # transient states that the poll cycle may have missed.
                if "mfa-get-otp-btn" in seen_transiently and self.br.find_elements(
                    By.ID, "mfa-get-otp-btn"
                ):
                    self.process_otp()
                    return
                if "proceedBtn" in seen_transiently and self.br.find_elements(
                    By.ID, "proceedBtn"
                ):
                    self.br.find_element(By.ID, "proceedBtn").click()
                    continue
                self.handle_login_error()
                return

            last = found[-1]

            if "is invalid" in last:
                self.throw(
                    "The password you've set in Bank Integration Settings is incorrect."
                )

            elif last == "fldOldPass":
                self.throw(
                    "The password you've set has expired. "
                    "Please set a new password manually and update the same in Bank Integration Settings."
                )

            elif last == "proceedBtn":
                # "Already logged in" dialog — click Proceed and loop to
                # detect what screen comes next.
                self.get_element("proceedBtn", "id", now=True).click()
                continue

            elif last == "mfa-get-otp-btn":
                self.process_otp()
                return

            elif last == "fldAnswer":
                self.process_security_questions()
                return

            elif last == "bb-retail-layout":
                # bb-retail-layout is the Angular app shell — it may be present
                # on the OTP screen too. Check explicitly before declaring success.
                if self.br.find_elements(By.ID, "mfa-get-otp-btn"):
                    self.process_otp()
                else:
                    self.login_success()
                return

            else:
                # Unknown state
                self.handle_login_error()
                return

        # Looped 3 times without reaching a terminal state
        self.handle_login_error()

    def process_otp(self):
        mobile_no = email_id = None

        try:
            self.wait_until(
                AnyEC(
                    EC.visibility_of_element_located(
                        (
                            By.XPATH,
                            '//button[contains(@class, "bb-button-bar__button") and contains(@class, "btn-primary") and normalize-space(text())="Get OTP"]',
                        )
                    ),
                    # mfa-get-otp-btn is kept display:none by Angular — it exists in the
                    # DOM immediately but is never visible, so presence_of_element_located
                    # must be used here instead of visibility_of_element_located.
                    EC.presence_of_element_located((By.ID, "mfa-get-otp-btn")),
                ),
                throw=False,
            )
        except:
            self.throw(
                "Failed to find Get Otp Button. Payment is not successful.",
                screenshot=True,
            )

        if (
            '//button[contains(@class, "bb-button-bar__button") and contains(@class, "btn-primary") and normalize-space(text())="Get OTP"]'
            == self.br._found_element[-1]
        ):
            try:
                # Click the label wrapping the "SMS + email" radio option.
                # The <input type="radio"> is visually hidden (::before pseudo-element
                # renders the circle), so clicking the <input> directly has no effect.
                # Clicking the <label data-role="radio-group-option"> that wraps it
                # is the correct trigger for Angular's radio-group component.
                # We target the label whose child span contains both "SMS" and "email"
                # to select the combined SMS+email OTP channel.
                email_mobile_otp_label = self.get_element(
                    '//label[@data-role="radio-group-option"][.//span[contains(text(),"SMS") and contains(text(),"email")]]',
                    "xpath",
                )
                self.br.execute_script("arguments[0].click();", email_mobile_otp_label)
            except Exception:
                pass
            get_otp_btn = self.get_element(
                '//button[contains(@class, "bb-button-bar__button") and contains(@class, "btn-primary") and normalize-space(text())="Get OTP"]',
                "xpath",
                now=True,
            )
            get_otp_btn.click()
        elif "mfa-get-otp-btn" == self.br._found_element[-1]:
            try:
                email_mobile_otp_radio = self.get_element("channel-BOTH", "id")
                email_mobile_otp_radio.click()
            except Exception:
                pass
            otp_btn = self.get_element("mfa-get-otp-btn", "id", now=True)
            self.br.execute_script("arguments[0].click();", otp_btn)

        # Button exists in DOM but display:none (Angular) — use JS click
        # otp_btn = self.get_element("mfa-get-otp-btn", "id", now=True)
        # self.br.execute_script("arguments[0].click();", otp_btn)

        ## till here the workflow is working. cleaning needs to be done.

        # try:
        #     mobile_no = self.get_element(
        #         '//*[@name="fldMobile"]/../following-sibling::td[last()]',
        #         "xpath",
        #         now=True,
        #         throw=False,
        #     ).text
        # except NoSuchElementException:
        #     pass

        # try:
        #     self.get_element("fldEmailid", now=True, throw=False).click()
        #     email_id = self.get_element(
        #         '//*[@name="fldEmailid"]/../following-sibling::td[last()]',
        #         "xpath",
        #         now=True,
        #         throw=False,
        #     ).text
        # except NoSuchElementException:
        #     pass
        self.br.switch_to.default_content()
        input_msg = ""
        try:
            input_msg = self.get_element('label[for="otpValue"]', "css_selector").text
        except Exception:
            pass
        # self.br.execute_script("return fireOtp();")

        frappe.publish_realtime(
            "get_bank_otp",
            {
                "message": input_msg,
                "uid": self.uid,
                "bank_name": self.bank_name,
                "logged_in": self.logged_in,
            },
            user=frappe.session.user,
            doctype=self.doctype,
            docname=self.docname,
        )

        self.save_for_later()

    def process_security_questions(self):
        frappe.publish_realtime(
            "get_bank_answers",
            {
                "questions": self.get_question_map(),
                "uid": self.uid,
                "bank_name": self.bank_name,
                "logged_in": self.logged_in,
            },
            user=frappe.session.user,
            doctype=self.doctype,
            docname=self.docname,
        )

        self.save_for_later()

    def get_question_map(self, get_fields=False):
        question_elements = self.br.find_elements(By.NAME, "fldQuestionText")
        answer_elements = self.br.find_elements(By.NAME, "fldAnswer")

        question_map = {}
        i = 0

        for element in question_elements:
            if not get_fields:
                value = element.get_attribute("value")
            else:
                try:
                    value = answer_elements[i]
                except IndexError:
                    self.throw(
                        "Could not find fields to input secret answers. Exiting.."
                    )

            i += 1
            question_map["question_" + str(i)] = value

        return question_map

    def submit_otp_or_answers(self, otp=None, answers=None):
        if not otp and not answers:
            self.throw("Invalid response received. Exiting..")

        if otp:
            self.submit_otp(otp)
        else:
            self.submit_answers(answers)

    def submit_otp(self, otp):
        otp_field = self.get_element("otpValue", "id")
        otp_field.send_keys(otp)
        submit_btn = self.get_element(
            '//button[contains(@class, "bb-button-bar__button") and contains(@class, "btn-primary") and normalize-space(text())="Submit"]',
            "xpath",
        )
        submit_btn.click()
        # self.br.execute_script("return authOtp();")

    def submit_answers(self, answers):
        field_map = self.get_question_map(True)
        for fieldname, element in field_map.items():
            element.clear()
            element.send_keys(answers.get(fieldname))

        self.br.execute_script("return submit_challenge();")

    def continue_login(self, otp=None, answers=None):
        self.submit_otp_or_answers(otp, answers)
        try:
            self.get_element(
                '//h1[@data-role="headings" and contains(@class,"bb-heading-widget__heading")]',
                "xpath",
                throw=False,
            )
        except TimeoutException:
            self.handle_login_error()
        else:
            self.login_success()

    def handle_login_error(self):
        try:
            alert = self.br.switch_to.alert.text
        except NoAlertPresentException:
            self.throw("Login failed")
        else:
            self.throw(alert)

    def login_success(self):
        self.logged_in = 1

        if self.doctype == "Bank Integration Settings":
            self.show_msg("Credentials verified successfully!")
            self.emit_js("setTimeout(() => {frappe.hide_msgprint()}, 2000);")
            self.logout()
        elif self.doctype == "Payment Entry":
            self.show_msg("Login Successful! Processing payment..")
            self.make_payment()
        elif self.doctype == "Bank Account":
            self.fetch_transactions()

    def logout(self):
        if self.logged_in:
            self.br.switch_to.default_content()
            logout_btn1 = self.br.find_element(
                By.CSS_SELECTOR,
                'div.logout-icon-container[aria-label="Logout"][role="button"]',
            )
            self.br.execute_script("arguments[0].click();", logout_btn1)
            self.br.switch_to.default_content()
            logout_btn2 = self.br.find_element(
                By.XPATH,
                '//button[contains(@class,"bb-button-bar__button") and normalize-space(text())="Logout"]',
            )
            self.br.execute_script("arguments[0].click();", logout_btn2)
            time.sleep(1)

        self.delete_cache()
        self.br.quit()

    def make_payment(self):
        self.br.switch_to.default_content()

        # Use a JS click on the Angular routerlink anchor instead of self.br.get()
        # or a normal Selenium click. self.br.get() causes a full page reload which
        # HDFC detects and terminates the session. A JS click fires the Angular
        # router internally without any HTTP navigation, and works regardless of
        # whether the element is visible or the navbar is collapsed.
        clicked = self.br.execute_script("""
            var el = document.querySelector("a[routerlink='/transfers/send-money']");
            if (el) { el.click(); return true; }
            return false;
        """)
        if not clicked:
            self.throw(
                "Could not find the 'Send Money' navigation link. The HDFC portal layout may have changed."
            )

        self.wait_until(EC.url_contains("/transfers/send-money"))

        to_account_input_box = self.get_element("typeahead-template", "id")
        to_account_input_box.click()
        to_account_input_box.send_keys(self.data.to_account, Keys.ENTER)
        wait = WebDriverWait(self.br, 10)
        option = wait.until(
            EC.element_to_be_clickable(
                (By.CSS_SELECTOR, "li.custom-to-account div.select-account-body")
            )
        )
        option.click()

        if self.data.transfer_type == "Transfer within the bank":
            self.make_payment_within_bank()
        elif self.data.transfer_type == "Transfer to other bank (NEFT)":
            self.make_neft_payment()

    def make_payment_within_bank(self):
        # self.br.execute_script("return formSubmit_new('TPT');")

        # self.switch_to_frame("main_part")
        # self.get_element("selectselAcct0", "id")

        # # from account
        # from_account = self.get_element("selAcct", now=True)
        # self.click_option(
        #     from_account,
        #     self.data.from_account,
        #     "The account number you entered in Bank Integration Settings could not be found in NetBanking",
        # )

        # to account
        # beneficiary = self.get_element("fldToAcct", now=True)
        # self.click_option(
        #     beneficiary,
        #     self.data.to_account,
        #     "Unable to find a beneficiary associated with the party's account number",
        # )
        # amount
        amt = self.get_element("transfer-amount-input", "id")
        amt.clear()
        amt.send_keys("%.2f" % self.data.amount)

        # description - target the actual input inside the cb-input-text-ui wrapper
        # desc = self.get_element("cb-input-text-ui#note input", "css_selector", now=True)
        desc = self.get_element('input[data-role="input"]', "css_selector")
        desc.clear()
        desc.send_keys(self.data.payment_desc)

        # continue
        continue_btn = self.get_element(
            'button[type="submit"].btn-primary.btn.btn-md.btn-block',
            "css_selector",
            now=True,
        )
        self.br.execute_script("arguments[0].scrollIntoView({block: 'center'});", continue_btn)
        try:
            continue_btn.click()
        except Exception:
            self.br.execute_script("arguments[0].click();", continue_btn)

        # Terms & conditions checkbox
        checkbox_label = self.get_element(
            'span.bb-input-checkbox__content[data-role="checkbox-label"]',
            "css_selector",
        )
        checkbox_label.click()

        # Confirm
        confirm_btn = self.get_element(
            'button.confirm-btn[aria-label="Confirm Transfer"]',
            "css_selector",
        )
        confirm_btn.click()
        # self.switch_to_frame("main_part")
        self.br.switch_to.default_content()

        # self.br.execute_script("return issue_click();")

        # self.switch_to_frame("main_part")

        # get_otp_btn = self.get_element("", "xpath", now=True)
        # get_otp_btn.click()

        try:
            self.wait_until(
                AnyEC(
                    EC.visibility_of_element_located(
                        (
                            By.XPATH,
                            '//button[contains(@class, "bb-button-bar__button") and contains(@class, "btn-primary") and normalize-space(text())="Get OTP"]',
                        )
                    ),
                    EC.visibility_of_element_located((By.NAME, "fldAnswer")),
                    EC.visibility_of_element_located(
                        (By.CSS_SELECTOR, "span.success-tick")
                    ),
                ),
                throw=False,
            )
        except:
            self.throw(
                "Failed to find indication of successful payment. Please check if payment has been processed manually.",
                screenshot=True,
            )

        if (
            '//button[contains(@class, "bb-button-bar__button") and contains(@class, "btn-primary") and normalize-space(text())="Get OTP"]'
            == self.br._found_element[-1]
        ):
            self.process_otp()
        elif "fldAnswer" == self.br._found_element[-1]:
            self.process_security_questions()
        else:
            self.payment_success()

    def make_neft_payment(self):
        # self.br.execute_script("return formSubmit_new('NEFT');")
        amt = self.get_element("transfer-amount-input", "id")
        amt.clear()
        amt.send_keys("%.2f" % self.data.amount)

        # description - target the actual input inside the cb-input-text-ui wrapper
        # desc = self.get_element("cb-input-text-ui#note input", "css_selector", now=True)
        desc = self.get_element('input[data-role="input"]', "css_selector")
        desc.clear()
        desc.send_keys(self.data.payment_desc)

        # continue
        continue_btn = self.get_element(
            'button[type="submit"][aria-label="Continue transfer"]',
            "css_selector",
            now=True,
        )
        self.br.execute_script(
            "arguments[0].scrollIntoView({block: 'center'});", continue_btn
        )
        try:
            continue_btn.click()
        except Exception:
            self.br.execute_script("arguments[0].click();", continue_btn)

        # Terms & conditions checkbox
        checkbox_label = self.get_element(
            'span.bb-input-checkbox__content[data-role="checkbox-label"]',
            "css_selector",
        )
        checkbox_label.click()

        # Confirm
        confirm_btn = self.get_element(
            'button.confirm-btn[aria-label="Confirm Transfer"]',
            "css_selector",
        )
        confirm_btn.click()
        # self.switch_to_frame("main_part")
        self.br.switch_to.default_content()

        try:
            self.wait_until(
                AnyEC(
                    EC.visibility_of_element_located(
                        (
                            By.XPATH,
                            '//button[contains(@class, "bb-button-bar__button") and contains(@class, "btn-primary") and normalize-space(text())="Get OTP"]',
                        )
                    ),
                    EC.visibility_of_element_located((By.NAME, "fldAnswer")),
                    EC.visibility_of_element_located(
                        (By.CSS_SELECTOR, "span.success-tick")
                    ),
                ),
                throw=False,
            )
        except:
            self.throw(
                "Failed to find indication of successful payment. Please check if payment has been processed manually.",
                screenshot=True,
            )

        if (
            '//button[contains(@class, "bb-button-bar__button") and contains(@class, "btn-primary") and normalize-space(text())="Get OTP"]'
            == self.br._found_element[-1]
        ):
            self.process_otp()

        # self.switch_to_frame("main_part")
        # self.get_element("selectselAcct0", "id")

        # # from account
        # from_account = self.get_element("selAcct", now=True)
        # self.click_option(
        #     from_account,
        #     self.data.from_account,
        #     "The account number you entered in Bank Integration Settings could not be found in NetBanking",
        # )

        # to account
        # try:
        #     account_index = self.br.execute_script(
        #         'return l_beneacct.indexOf("{}");'.format(self.data.to_account)
        #     )
        # except:
        #     self.throw("Failed to select beneficiary in Netbanking")

        # if account_index == -1:
        #     self.throw("Beneficary account number not found in Netbanking")
        # else:
        #     account_index = str(account_index)

        # beneficiary = self.get_element("fldBeneId", now=True)
        # self.click_option(
        #     beneficiary,
        #     account_index,
        #     "Unable to find a beneficiary associated with the party's account number",
        #     exact=True,
        # )

        # time.sleep(0.5)
        # if (
        #     self.get_element("fldBeneAcct", now=True).get_attribute("value") or ""
        # ).strip() != self.data.to_account:
        #     self.throw(
        #         "Incorrect account selected. Please contact developer for support."
        #     )

        # # description
        # desc = self.get_element("fldTxnDesc", now=True)
        # desc.clear()
        # desc.send_keys(self.data.payment_desc)

        # # amount
        # amt = self.get_element("fldTxnAmount", now=True)
        # amt.clear()
        # amt.send_keys("%.2f" % self.data.amount)

        # communication type
        # comm_type = self.get_element("fldComMode", now=True)
        # self.click_option(
        #     comm_type,
        #     self.data.comm_type,
        #     "Unable to select communication type in NEFT form",
        #     compare_text=True,
        # )

        # # communication value
        # comm_value = self.get_element("fldMobileEmail", now=True)
        # comm_value.clear()
        # comm_value.send_keys(self.data.comm_value)

        # # accept terms
        # self.get_element(
        #     "//*[@name='fldtc']/preceding-sibling::span[@class='checkbox']",
        #     "xpath",
        #     now=True,
        # ).click()

        # # continue
        # self.br.execute_script("return formSubmit();")

        # # confirm
        # self.switch_to_frame("main_part")
        # self.br.execute_script("return formSubmit();")

        # self.switch_to_frame("main_part")

        # try:
        #     self.wait_until(
        #         AnyEC(
        #             EC.visibility_of_element_located((By.NAME, "fldMobile")),
        #             EC.visibility_of_element_located((By.NAME, "fldAnswer")),
        #             EC.visibility_of_element_located(
        #                 (By.XPATH, "//td[contains(text(),'Reference Number')]")
        #             ),
        #         ),
        #         throw=False,
        #     )
        # except:
        #     self.throw(
        #         "Failed to find indication of successful payment. Please check is payment has been processed manually.",
        #         screenshot=True,
        #     )

        elif "fldAnswer" == self.br._found_element[-1]:
            self.process_security_questions()
        else:
            self.payment_success()

    def click_option(
        self, element, to_click, error=None, exact=False, compare_text=False
    ):
        for option in element.find_elements(By.TAG_NAME, "option"):
            if not compare_text:
                val = option.get_attribute("value")
            else:
                val = (option.text or "").strip()
            if not val:
                continue

            val = val.strip()

            if (exact and to_click == val) or to_click in val:
                option.click()
                break
        else:
            if error:
                self.throw(error)

    def continue_payment(self, otp=None, answers=None):
        self.br.switch_to.default_content()
        self.submit_otp_or_answers(otp, answers)

        try:
            self.br.switch_to.default_content()

            if self.data.transfer_type == "Transfer within the bank":
                self.get_element("span.success-tick", "css_selector")

            elif self.data.transfer_type == "Transfer to other bank (NEFT)":
                self.get_element("span.success-tick", "css_selector")

        except TimeoutException:
            self.throw(
                "{} authentication failed. Exiting..".format(
                    "OTP" if otp else "Security questions"
                ),
                screenshot=True,
            )
        else:
            self.payment_success()

    def payment_success(self):
        self.br.switch_to.default_content()

        details_button = self.get_element("showHideBtn", "id")
        details_button.click()

        save_file(
            self.docname + " Online Payment Screenshot.png",
            self.br.get_screenshot_as_png(),
            self.doctype,
            self.docname,
            is_private=1,
        )

        ref_no = "-"
        if self.data.transfer_type == "Transfer within the bank":
            try:
                ref_no = (
                    self.get_element(
                        "//div[normalize-space(text())='Transaction ID']/following-sibling::div[contains(@class,'bb-text-medium-bold')]",
                        "xpath",
                        now=True,
                        throw=False,
                    ).text
                    or "-"
                ).strip()
            except Exception:
                pass
        else:
            # Fallback for old NEFT UI (Reference Number in <td>)
            # if ref_no == "-" and self.data.transfer_type == "Transfer to other bank (NEFT)":
            try:
                ref_no = (
                    self.get_element(
                        '//div[contains(@class,"bb-support--sub-title") and normalize-space(text())="Reference ID"]/following-sibling::div[contains(@class,"bb-text-medium-bold")]',
                        "xpath",
                    ).text
                    or "-"
                ).strip()
            except Exception:
                pass

        frappe.publish_realtime(
            "payment_success",
            {"ref_no": ref_no, "uid": self.uid},
            user=frappe.session.user,
            doctype="Payment Entry",
            docname=self.docname,
        )

        frappe.db.commit()
        self.logout()

    def fetch_transactions(self, from_date=None):
        def update_transactions(transactions, after_date, bank_account):
            trans_ids = frappe.get_all(
                "Bank Transaction",
                filters=[
                    ["creation", ">", add_days(after_date, -1)],
                    ["bank_account", "=", bank_account],
                ],
                fields="transaction_id",
            )
            existing_transactions = [item["transaction_id"] for item in trans_ids]
            count = 0
            closing_balance = 0
            for transaction in transactions:
                for key in ("Withdrawal", "Deposit", "Closing Balance"):
                    if transaction.get(key):
                        transaction[key] = flt(transaction[key])
                transaction["Cheque/Ref. No."] = str(
                    transaction["Cheque/Ref. No."]
                ).replace(".0", "")

                transaction_id = hashlib.sha224(str(transaction).encode()).hexdigest()

                if transaction_id in existing_transactions:
                    continue

                bank_transaction = frappe.get_doc({"doctype": "Bank Transaction"})

                bank_transaction.update(
                    {
                        "transaction_id": transaction_id,
                        "date": getdate(transaction["Date"]),
                        "description": transaction["Narration"],
                        "withdrawal": flt(transaction["Withdrawal"]),
                        "deposit": flt(transaction["Deposit"]),
                        "reference_number": transaction["Cheque/Ref. No."],
                        "closing_balance": flt(transaction["Closing Balance"]),
                        "bank_account": bank_account,
                        "unallocated_amount": abs(
                            flt(transaction["Deposit"]) - flt(transaction["Withdrawal"])
                        ),
                    }
                )
                bank_transaction.submit()
                count += 1
                closing_balance = flt(transaction["Closing Balance"])

            frappe.publish_realtime(
                "sync_transactions",
                {
                    "uid": self.uid,
                    "count": count,
                    "closing_balance": closing_balance,
                    "after_date": add_days(after_date, -1),
                },
                user=frappe.session.user,
            )

        self.switch_to_frame("main_part")
        self.switch_to_frame("left_menu")
        self.get_element("enquiryatag", selector_type="id", now=True).click()
        self.get_element("SIN_nohref", selector_type="id", now=True).click()

        self.switch_to_frame("main_part")
        self.get_element("selectselAccttype0", "id")
        self.click_option(
            self.get_element("selAccttype", now=True),
            "SCA",
            "Unable to select Account Type",
        )

        self.click_option(
            self.get_element("selAcct", now=True),
            self.data.from_account_no,
            "Please verify account number in Bank Integration Settings",
        )

        prev_valid_date = add_months(add_days(today(), -getdate().day + 1), -1)
        if not frappe.db.count(
            "Bank Transaction",
            filters={
                "bank_account": self.data.bank_account,
                "date": [">", prev_valid_date],
            },
        ):
            from_date = prev_valid_date
        else:
            from_date = frappe.get_all(
                "Bank Transaction",
                filters={"bank_account": self.data.bank_account},
                fields="date",
                order_by="creation desc",
                limit=1,
            )[0]["date"]
            if getdate(from_date) <= getdate(prev_valid_date):
                from_date = prev_valid_date
            from_date = add_days(from_date, -1)

        self.br.find_elements(By.CLASS_NAME, "radio")[1].click()

        self.get_element("frmDatePicker", selector_type="id", now=True).send_keys(
            getdate(from_date).strftime("%d/%m/%Y")
        )
        self.get_element("toDatePicker", selector_type="id", now=True).send_keys(
            getdate().strftime("%d/%m/%Y")
        )
        self.br.execute_script("return formSubmitbytype()")

        self.br.execute_script("$('.datatable').show()")
        transaction_tables = self.br.find_elements(By.CLASS_NAME, "datatable")

        if not transaction_tables:
            self.throw("No New Transactions found")
            self.logout()
            return

        transactions = _get_transactions(transaction_tables)

        self.logout()

        update_transactions(transactions, from_date, self.data.bank_account)


def _get_transactions(transaction_tables):
    from bs4 import BeautifulSoup

    transactions = []

    for table_element in transaction_tables:
        soup = BeautifulSoup(table_element.get_attribute("outerHTML"), "lxml")
        table = soup.find("table")

        if not table:
            continue

        rows = table.find_all("tr")
        if not rows:
            continue
        # First row is header
        headers = [th.text.strip() for th in rows[0].find_all("th")]

        # Remaining rows are data
        for row in rows[1:]:
            cells = row.find_all("td")

            # NOTE: Will not happen right?
            if len(cells) != len(headers):
                continue  # Skip incomplete rows

            transaction = {
                header: (cell.text.strip() or 0) for header, cell in zip(headers, cells)
            }

            transactions.append(transaction)

    transactions.reverse()  # To maintain chronological order
    return transactions
