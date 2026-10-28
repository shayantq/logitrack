# ---------- مرحله ۱: ساخت اپ React (فقط برای build؛ در image نهایی Node وجود ندارد) ----------
FROM node:22-alpine AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------- مرحله ۲: اپلیکیشن پایتون ----------
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /code

# نصب وابستگی‌ها در لایه جدا تا با هر تغییر کد دوباره نصب نشوند
COPY requirements.txt .
# pip بعد از نصب حذف می‌شود: در اجرا لازم نیست و کتابخانه‌های قدیمیِ داخلش (msgpack، urllib3، setuptools) در اسکن امنیتی image آسیب‌پذیر شناخته می‌شوند
RUN pip install -r requirements.txt && pip uninstall -y pip

# اجرای برنامه با کاربر غیر root
# پوشه media (لوگوها و فایل‌های آپلودی) از قبل با مالکیت app ساخته می‌شود تا volume داکر همین مالکیت را بگیرد
RUN useradd --create-home --uid 1000 app && mkdir -p /code/media && chown app:app /code/media

# فایل‌های اضافه (venv، .env، کش‌ها، node_modules و ...) با .dockerignore کنار گذاشته می‌شوند
COPY --chown=app:app . .
COPY --from=frontend --chown=app:app /frontend/dist /code/frontend/dist

USER app
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
