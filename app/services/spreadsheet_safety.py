"""
خنثی‌سازی فرمول در خروجی‌های اکسل و CSV (حمله «تزریق فرمول»).

متنی که کاربر وارد کرده (نام کالا، توضیح، نام مشتری و ...) اگر با = + - @ یا Tab/Enter شروع شود،
اکسل ممکن است آن را فرمول اجرا کند. در فایل xlsx خانه‌ها متن ذخیره می‌شوند (نه فرمول)
و در CSV یک ' به ابتدای متن اضافه می‌شود. عدد واقعی (مثل ‎-12.5) دست نمی‌خورد.
"""
import re

_TRIGGERS = ("=", "+", "-", "@", "\t", "\r")
_NUMBER = re.compile(r"^[+-]?\d+(?:[.,]\d+)?$")


def csv_cell(value):
    if isinstance(value, str) and value.startswith(_TRIGGERS) and value != "-" and not _NUMBER.match(value):
        return "'" + value
    return value


def neutralize_workbook(wb) -> None:
    """هر خانه‌ای که openpyxl فرمول تشخیص داده، متن ذخیره شود (اعتبارسنجی فهرست‌ها خانه نیستند و می‌مانند)."""
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                if cell.data_type == "f":
                    cell.data_type = "s"
