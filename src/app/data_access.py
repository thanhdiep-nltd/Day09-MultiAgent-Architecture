from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from langchain_core.tools import tool


class ShoppingDataStore:
    """Student scaffold for mock-data lookup."""

    def __init__(self, json_path: Path) -> None:
        # Load JSON and parse sections
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            raise RuntimeError(f"Failed to load mock data from {json_path}: {e}")

        self.metadata = data.get("metadata", {})
        self.customers = data.get("customers", [])
        self.orders = data.get("orders", [])
        self.vouchers = data.get("vouchers", [])

        # Build indexes for fast lookup
        self.customer_by_id = {c["customer_id"]: c for c in self.customers}
        self.order_by_id = {str(o["order_id"]): o for o in self.orders}

        self.orders_by_customer_id = defaultdict(list)
        for o in self.orders:
            self.orders_by_customer_id[o["customer_id"]].append(o)

        self.vouchers_by_customer_id = defaultdict(list)
        for v in self.vouchers:
            self.vouchers_by_customer_id[v["customer_id"]].append(v)

    def get_customer_by_id(self, customer_id: str) -> dict[str, Any]:
        customer = self.customer_by_id.get(customer_id)
        if customer:
            return {"status": "ok", "customer": customer}
        return {"status": "not_found", "customer_id": customer_id}

    def get_orders_by_customer_id(self, customer_id: str, limit: int = 10) -> dict[str, Any]:
        if customer_id not in self.customer_by_id:
            return {"status": "not_found", "customer_id": customer_id}
        orders = self.orders_by_customer_id.get(customer_id, [])
        # Sort by created_at descending if available, otherwise by order_id
        sorted_orders = sorted(
            orders,
            key=lambda x: x.get("created_at", str(x.get("order_id"))),
            reverse=True,
        )
        return {"status": "ok", "orders": sorted_orders[:limit]}

    def get_order_detail_by_order_id(self, order_id: str) -> dict[str, Any]:
        order = self.order_by_id.get(str(order_id))
        if order:
            return {"status": "ok", "order": order}
        return {"status": "not_found", "order_id": order_id}

    def get_vouchers_by_customer_id(
        self,
        customer_id: str,
        only_active: bool = False,
    ) -> dict[str, Any]:
        if customer_id not in self.customer_by_id:
            return {"status": "not_found", "customer_id": customer_id}
        vouchers = self.vouchers_by_customer_id.get(customer_id, [])
        if only_active:
            vouchers = [v for v in vouchers if v.get("status") == "active"]
        return {"status": "ok", "vouchers": vouchers}


def build_data_tools(store: ShoppingDataStore) -> list:
    @tool
    def get_customer_by_id(customer_id: str) -> dict[str, Any]:
        """Tra cứu thông tin chi tiết của khách hàng (tên, email, phân hạng thành viên, điểm tích lũy, số lượng voucher đã dùng trong tháng, v.v.) dựa vào customer_id (ví dụ: 'C001')."""
        return store.get_customer_by_id(customer_id)

    @tool
    def get_orders_by_customer_id(customer_id: str, limit: int = 10) -> dict[str, Any]:
        """Tra cứu danh sách đơn hàng gần đây của khách hàng dựa vào customer_id (ví dụ: 'C001'). Hỗ trợ giới hạn số lượng kết quả qua tham số limit."""
        return store.get_orders_by_customer_id(customer_id, limit)

    @tool
    def get_order_detail_by_order_id(order_id: str) -> dict[str, Any]:
        """Tra cứu thông tin chi tiết của một đơn hàng cụ thể (trạng thái đơn hàng, ngày dự kiến giao, tổng tiền, danh sách mặt hàng, quyền trả hàng can_return_now, v.v.) dựa vào order_id (ví dụ: '1971')."""
        return store.get_order_detail_by_order_id(order_id)

    @tool
    def get_vouchers_by_customer_id(customer_id: str, only_active: bool = False) -> dict[str, Any]:
        """Tra cứu danh sách các voucher của khách hàng dựa vào customer_id (ví dụ: 'C001'). Có thể lọc chỉ lấy voucher còn hạn sử dụng bằng cách truyền only_active=True."""
        return store.get_vouchers_by_customer_id(customer_id, only_active)

    return [
        get_customer_by_id,
        get_orders_by_customer_id,
        get_order_detail_by_order_id,
        get_vouchers_by_customer_id,
    ]
