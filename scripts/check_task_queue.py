"""بررسی واقعی اتصال broker و پاسخ worker، پیش از اجرای E2E یا پایان استقرار."""
from time import sleep

from app.celery_app import celery_app


def main() -> None:
    for attempt in range(6):
        replies = celery_app.control.ping(timeout=3)
        if any(reply.get("ok") == "pong" for node in replies for reply in node.values()):
            print("Celery worker is ready and responds through the broker.")
            return
        if attempt < 5:
            sleep(2)
    raise RuntimeError("Celery worker did not respond through the broker.")


if __name__ == "__main__":
    main()
