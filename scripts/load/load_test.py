"""
بار آزمایشی (ت۱۷). فقط روی localhost اجرا می‌شود؛ هر نتیجه برچسب محیط دارد و عدد ظرفیت سرور اصلی نیست.

    python scripts/load/load_test.py http://localhost:8004 --env "local 2cpu ..." --out result.json

کاربران و رمزها همان seed_demo_data هستند. METRICS_TOKEN از محیط خوانده می‌شود و DOCKER_PROJECT نام پروژه compose است.
"""
import argparse
import json
import os
import re
import statistics
import subprocess
import threading
import time
import uuid
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import httpx

READ_FLOWS = {
    "dashboard_action_center": "/action-center",
    "dashboard_business": "/home/business",
    "dashboard_stats": "/reports/stats",
    "inventory_products": "/inventory/products",
    "movement_history_500": "/inventory/movements?limit=500",
    "orders_list": "/orders/?limit=100",
    "picking_lists": "/picking/lists?status=active",
    "putaway_tasks": "/putaway/tasks?status=active",
    "tickets_list": "/tickets/",
}


def pct(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * q))]


def summarize(times: list[float], statuses: dict, seconds: float | None = None) -> dict:
    out = {"count": len(times), "statuses": dict(statuses)}
    if times:
        out.update(p50_ms=round(pct(times, .5) * 1000), p95_ms=round(pct(times, .95) * 1000), p99_ms=round(pct(times, .99) * 1000),
                   mean_ms=round(statistics.mean(times) * 1000))
    if seconds:
        out["per_second"] = round(len(times) / seconds, 1)
    return out


class Sampler(threading.Thread):
    """مصرف کانتینرها و pool را هر چند ثانیه می‌خواند و بیشینه را نگه می‌دارد."""

    def __init__(self, base: str, project: str):
        super().__init__(daemon=True)
        self.base, self.project = base, project
        self.stop_flag = threading.Event()
        self.peak_mem, self.peak_cpu = defaultdict(float), defaultdict(float)
        self.peak_pool, self.peak_queue = 0.0, 0.0

    def run(self):
        token = os.getenv("METRICS_TOKEN", "")
        while not self.stop_flag.wait(3):
            try:
                out = subprocess.run(["docker", "stats", "--no-stream", "--format", "{{.Name}}|{{.CPUPerc}}|{{.MemUsage}}"], capture_output=True, text=True, timeout=30).stdout
            except subprocess.TimeoutExpired:
                continue
            for line in out.splitlines():
                name, cpu, mem = line.split("|")
                if not name.startswith(self.project + "-"):
                    continue
                service = name[len(self.project) + 1:].rsplit("-", 1)[0]
                self.peak_cpu[service] = max(self.peak_cpu[service], float(cpu.rstrip("%")))
                match = re.match(r"([\d.]+)(KiB|MiB|GiB)", mem)
                if match:
                    self.peak_mem[service] = max(self.peak_mem[service], float(match[1]) * {"KiB": 1 / 1024, "MiB": 1, "GiB": 1024}[match[2]])
            if token:
                try:
                    text = httpx.get(f"{self.base}/internal/metrics", headers={"Authorization": f"Bearer {token}"}, timeout=10).text
                    for name, attr in (("pasineh_db_pool_in_use", "peak_pool"), ("pasineh_celery_queue_depth", "peak_queue")):
                        found = re.search(rf"^{name} ([\d.]+)", text, re.M)
                        if found:
                            setattr(self, attr, max(getattr(self, attr), float(found[1])))
                except httpx.HTTPError:
                    pass


class Api:
    def __init__(self, base: str, token: str | None = None):
        self.client = httpx.Client(base_url=base, timeout=120, headers={"Authorization": f"Bearer {token}"} if token else {})

    def call(self, method: str, path: str, **kw) -> httpx.Response:
        return self.client.request(method, path, **kw)

    def ok(self, method: str, path: str, **kw):
        res = self.call(method, path, **kw)
        if res.status_code >= 300:
            raise RuntimeError(f"{method} {path} -> {res.status_code}: {res.text[:200]}")
        return res.json() if res.content else None


def login(base: str, username: str, password: str) -> tuple[str, int, float]:
    started = time.perf_counter()
    res = httpx.post(f"{base}/auth/token", data={"username": username, "password": password}, timeout=60)
    return (res.json().get("access_token") if res.status_code == 200 else ""), res.status_code, time.perf_counter() - started


def timed_reads(base: str, token: str, path: str, workers: int, seconds: int) -> dict:
    deadline = time.perf_counter() + seconds
    times: list[float] = []
    statuses: dict = defaultdict(int)
    lock = threading.Lock()

    def worker():
        api = Api(base, token)
        while time.perf_counter() < deadline:
            started = time.perf_counter()
            try:
                code = api.call("GET", path).status_code
            except httpx.HTTPError as error:
                code = type(error).__name__
            with lock:
                times.append(time.perf_counter() - started)
                statuses[str(code)] += 1

    with ThreadPoolExecutor(workers) as pool:
        for _ in range(workers):
            pool.submit(worker)
    return summarize(times, statuses, seconds)


def run_steps(fn, workers: int, iterations: int) -> dict:
    """fn(index) یک نگاشت نام قدم به (زمان، وضعیت) برمی‌گرداند."""
    steps: dict = defaultdict(lambda: ([], defaultdict(int)))
    lock = threading.Lock()
    errors: list[str] = []

    def one(index):
        try:
            for name, spent, code in fn(index):
                with lock:
                    steps[name][0].append(spent)
                    steps[name][1][str(code)] += 1
        except Exception as error:
            with lock:
                errors.append(str(error)[:200])

    started = time.perf_counter()
    with ThreadPoolExecutor(workers) as pool:
        list(pool.map(one, range(iterations)))
    spent = time.perf_counter() - started
    result = {name: summarize(times, codes, spent) for name, (times, codes) in steps.items()}
    if errors:
        result["errors"] = {"count": len(errors), "first": errors[0]}
    return result


class Flows:
    def __init__(self, base: str, admin_token: str, manager_token: str):
        self.base, self.admin, self.manager = base, Api(base, admin_token), Api(base, manager_token)
        self.admin_token, self.manager_token = admin_token, manager_token
        self.run = uuid.uuid4().hex[:6].upper()
        me = self.manager.ok("GET", "/users/me")
        self.warehouse = me["warehouse_id"]
        code = f"LD{self.run}"
        for suffix, kind in (("RCV", "receiving"), ("BIN", "storage"), ("STG", "staging")):
            self.manager.ok("POST", f"/warehouses/{self.warehouse}/locations", json={"code": f"{code}-{suffix}", "level": "bin", "location_type": kind})
        locations = {loc["code"]: loc for loc in self.manager.ok("GET", f"/warehouses/{self.warehouse}/locations")}
        self.receiving, self.bin, self.staging = (locations[f"{code}-{s}"] for s in ("RCV", "BIN", "STG"))
        self.product = self.admin.ok("POST", "/inventory/products", json={
            "name": f"کالای بار {self.run}", "sku": f"LOAD-{self.run}", "price": 1000, "weight_kg": 1, "initial_quantity": 100_000, "warehouse_id": self.warehouse})
        self.product = self.product.get("product", self.product)
        self.partner = self.admin.ok("POST", "/partners/", json={"name": f"تأمین‌کننده بار {self.run}", "is_supplier": True})
        vehicles = self.admin.ok("GET", "/vehicles/")
        self.vehicle = next(v for v in vehicles if v.get("driver_id") and v.get("status") not in ("inactive", "maintenance"))

    def _step(self, api: Api, name: str, method: str, path: str, **kw):
        started = time.perf_counter()
        res = api.call(method, path, **kw)
        return (name, time.perf_counter() - started, res.status_code), res

    def receive_and_putaway(self, index: int):
        api, out = Api(self.base, self.manager_token), []
        step, res = self._step(api, "receipt_create", "POST", "/inbound/receipts", json={
            "receipt_type": "purchase", "warehouse_id": self.warehouse, "partner_id": self.partner["id"], "external_ref": uuid.uuid4().hex[:20], "lines": [{"product_id": self.product["id"], "expected_quantity": 2}]})
        out.append(step)
        if res.status_code >= 300:
            raise RuntimeError(f"receipt {res.status_code}: {res.text[:160]}")
        receipt = res.json()
        step, res = self._step(api, "receipt_receive", "POST", f"/inbound/receipts/{receipt['id']}/receive", headers={"Idempotency-Key": uuid.uuid4().hex}, json={
            "location_id": self.receiving["id"], "lines": [{"line_id": receipt["lines"][0]["id"], "quantity": 2}]})
        out.append(step)
        if res.status_code >= 300:
            raise RuntimeError(f"receive {res.status_code}: {res.text[:160]}")
        tasks = api.ok("GET", f"/putaway/tasks?status=active&receipt_id={receipt['id']}")
        if not tasks:
            raise RuntimeError("putaway task was not created")
        step, res = self._step(api, "putaway_execute", "POST", f"/putaway/tasks/{tasks[0]['id']}/execute", headers={"Idempotency-Key": uuid.uuid4().hex}, json={
            "product_scan": self.product["sku"], "source_scan": self.receiving["code"], "destination_scan": self.bin["code"], "quantity": tasks[0]["remaining"]})
        out.append(step)
        if res.status_code >= 300:
            raise RuntimeError(f"putaway {res.status_code}: {res.text[:160]}")
        return out

    def order_pick_dispatch(self, index: int):
        admin, manager, out = Api(self.base, self.admin_token), Api(self.base, self.manager_token), []
        start = datetime.now(timezone.utc) - timedelta(hours=1)
        step, res = self._step(admin, "order_create", "POST", "/orders/", json={
            "items": [{"product_id": self.product["id"], "quantity": 1}], "customer": {"name": "مشتری بار", "mobile": "09121112233"},
            "destination_province": "قزوین", "destination_city": "قزوین", "destination_address": "خیابان بار پلاک ۱", "size": "s", "priority": False,
            "delivery_window_start": start.isoformat(), "delivery_window_end": (start + timedelta(hours=10)).isoformat(),
            "warehouse_id": self.warehouse, "vehicle_id": self.vehicle["id"], "auto_assign": False})
        out.append(step)
        if res.status_code >= 300:
            raise RuntimeError(f"order {res.status_code}: {res.text[:160]}")
        order = res.json()
        step, res = self._step(manager, "pick_list_create", "POST", "/picking/lists", json={
            "warehouse_id": self.warehouse, "strategy": "single", "order_ids": [order["id"]], "staging_location_id": self.staging["id"]})
        out.append(step)
        if res.status_code >= 300:
            raise RuntimeError(f"pick list {res.status_code}: {res.text[:160]}")
        pick_list = res.json()
        for line in pick_list["lines"]:
            step, picked = self._step(manager, "pick_line", "POST", f"/picking/lines/{line['id']}/pick", headers={"Idempotency-Key": uuid.uuid4().hex}, json={
                "source_scan": line["location_code"] or pick_list["warehouse_code"], "product_scan": self.product["sku"], "quantity": line["quantity"]})
            out.append(step)
            if picked.status_code >= 300:
                raise RuntimeError(f"pick {picked.status_code}: {picked.text[:160]}")
        for status in ("picked_up", "in_transit", "delivered"):
            step, res = self._step(admin, f"status_{status}", "PUT", f"/orders/{order['id']}/status", json={"order_status": status})
            out.append(step)
        return out

    def report(self, index: int, heavy: bool = False):
        api = Api(self.base, self.admin_token)
        started = time.perf_counter()
        res = api.call("POST", "/reports/export/orders/excel" if heavy else "/reports/export/inventory/excel")
        out = [("report_queue", time.perf_counter() - started, res.status_code)]
        if res.status_code >= 300:
            return out
        task = res.json()["task_id"]
        while time.perf_counter() - started < 300:
            state = api.ok("GET", f"/reports/task-status/{task}")["status"]
            if state not in ("pending", "started", "running"):
                out.append(("report_total_orders_excel" if heavy else "report_total_inventory_excel", time.perf_counter() - started, state))
                return out
            time.sleep(0.5)
        out.append(("report_total", 300.0, "timeout"))
        return out


def stats(base: str) -> dict:
    token = os.getenv("METRICS_TOKEN", "")
    if not token:
        return {}
    text = httpx.get(f"{base}/internal/metrics", headers={"Authorization": f"Bearer {token}"}, timeout=20).text
    routes: dict = defaultdict(dict)
    for key, route, value in re.findall(r'^pasineh_http_db_queries_(sum|count)\{route="([^"]+)"\} (\S+)', text, re.M):
        routes[route][key] = float(value)
    return {route: round(v["sum"] / v["count"], 1) for route, v in routes.items() if v.get("count")}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("base")
    parser.add_argument("--env", required=True, help="برچسب محیط آزمون")
    parser.add_argument("--out", required=True)
    parser.add_argument("--seconds", type=int, default=15)
    parser.add_argument("--levels", default="1,5,20")
    args = parser.parse_args()
    host = urlparse(args.base).hostname
    if host not in ("localhost", "127.0.0.1"):
        raise SystemExit("بار آزمایشی فقط روی localhost اجرا می‌شود.")
    base = args.base.rstrip("/")
    project = os.getenv("DOCKER_PROJECT", "pasineh_load")
    sampler = Sampler(base, project)
    sampler.start()
    result: dict = {"environment": args.env, "at": datetime.now(timezone.utc).isoformat(), "levels": {}}

    logins = []
    codes: dict = defaultdict(int)
    with ThreadPoolExecutor(3) as pool:
        for _, code, spent in pool.map(lambda _: login(base, "qazvin_admin", "admin123"), range(30)):
            logins.append(spent)
            codes[str(code)] += 1
    result["login_concurrency_3"] = summarize(logins, codes)

    admin = login(base, "qazvin_admin", "admin123")[0]
    manager = login(base, "qazvin_manager", "manager123")[0]
    flows = Flows(base, admin, manager)

    for level in [int(v) for v in args.levels.split(",")]:
        result["levels"][level] = {}
        for name, path in READ_FLOWS.items():
            token = manager if name in ("picking_lists", "putaway_tasks") else admin
            result["levels"][level][name] = timed_reads(base, token, path, level, args.seconds)
            print(level, name, result["levels"][level][name], flush=True)

    result["receive_putaway"] = {f"workers_{w}": run_steps(flows.receive_and_putaway, w, n) for w, n in ((1, 20), (5, 50))}
    print(result["receive_putaway"], flush=True)
    result["order_pick_dispatch"] = {f"workers_{w}": run_steps(flows.order_pick_dispatch, w, n) for w, n in ((1, 20), (5, 40))}
    print(result["order_pick_dispatch"], flush=True)
    result["reports_inventory"] = run_steps(lambda i: flows.report(i), 3, 6)
    result["reports_orders_heavy"] = run_steps(lambda i: flows.report(i, heavy=True), 2, 4)
    print(result["reports_inventory"], result["reports_orders_heavy"], flush=True)

    result["avg_queries_per_request"] = stats(base)
    sampler.stop_flag.set()
    sampler.join(timeout=40)
    result["peak_memory_mib"] = {k: round(v) for k, v in sampler.peak_mem.items()}
    result["peak_cpu_percent"] = {k: round(v) for k, v in sampler.peak_cpu.items()}
    result["peak_pool_in_use"] = sampler.peak_pool
    result["peak_queue_depth"] = sampler.peak_queue
    with open(args.out, "w", encoding="utf-8") as out:
        json.dump(result, out, ensure_ascii=False, indent=1)
    print("done", result["peak_memory_mib"], result["peak_pool_in_use"], result["peak_queue_depth"], flush=True)


if __name__ == "__main__":
    main()
