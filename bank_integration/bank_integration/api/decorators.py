from frappe import _dict
from functools import wraps

def set_correct_payment_data(func):
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        if getattr(self, "bulk_payments", None):
            if self.remove_payment:
                data = _dict(self.bulk_payments.pop())
            else:
                data = self.data
        else:
            data = getattr(self, "data", None)

        if not data:
            raise Exception("No payment data available")

        self.data = data

        try:
            return func(self, *args, **kwargs)
        except Exception:
            self.throw("Some internal error")

    return wrapper
