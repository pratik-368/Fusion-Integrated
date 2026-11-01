from django.db.models import Q

from fusion_auth.client import IamUnavailable
from modules.directory import contracts as directory
from modules.psm.models import (
    AuditEvent,
    DiscrepancyCase,
    GoodsReceipt,
    Indent,
    InventoryBalance,
    Policy,
    PurchaseOrder,
    StockTransfer,
    Vendor,
)


DEPARTMENT_ROLES = {"department_admin", "department_head"}


def department_scope(actor):
    role = (getattr(actor, "active_role", None) or "").strip().lower().replace(" ", "_")
    if role not in DEPARTMENT_ROLES:
        return None
    try:
        user = directory.get_users([actor.user_id]).get(actor.user_id)
    except (IamUnavailable, OSError):
        return set()
    if user is None or not user.department:
        return set()
    row = Policy.objects.filter(key="department_id_by_name", active=True).first()
    mapping = row.value if row else None
    if not isinstance(mapping, dict):
        return set()
    department_id = mapping.get(user.department) or mapping.get(user.department.strip().lower())
    try:
        return {int(department_id)}
    except (TypeError, ValueError):
        return set()


def indents_for(actor, *, own=False):
    qs = Indent.objects.all()
    if own:
        return qs.filter(requestor_id=actor.user_id)
    if actor.has_permission("psm.indent.view"):
        scope = department_scope(actor)
        if scope is not None:
            return qs.filter(department_id__in=scope)
        return qs
    return qs.filter(requestor_id=actor.user_id)


def inventory_for(actor):
    qs = InventoryBalance.objects.all()
    scope = department_scope(actor)
    if scope is not None:
        return qs.filter(Q(department_id__in=scope) | Q(department_id__isnull=True))
    return qs


def vendors_for(actor):
    return Vendor.objects.filter(active=True)


def purchase_orders_for(actor):
    qs = PurchaseOrder.objects.select_related("vendor", "indent")
    scope = department_scope(actor)
    if scope is not None:
        return qs.filter(indent__department_id__in=scope)
    if actor.has_permission("psm.procurement.manage") or actor.has_permission("psm.invoice.manage"):
        return qs
    return qs.filter(indent__requestor_id=actor.user_id)


def receipts_for(actor):
    qs = GoodsReceipt.objects.select_related("purchase_order__indent")
    scope = department_scope(actor)
    if scope is not None:
        return qs.filter(purchase_order__indent__department_id__in=scope)
    if actor.has_permission("psm.procurement.manage") or actor.has_permission("psm.invoice.manage"):
        return qs
    return qs.filter(purchase_order__indent__requestor_id=actor.user_id)


def discrepancies_for(actor):
    qs = DiscrepancyCase.objects.select_related("receipt__purchase_order__indent")
    scope = department_scope(actor)
    if scope is not None:
        return qs.filter(receipt__purchase_order__indent__department_id__in=scope)
    return qs


def transfers_for(actor):
    qs = StockTransfer.objects.all()
    scope = department_scope(actor)
    if scope is not None:
        return qs.filter(Q(source_department_id__in=scope) | Q(destination_department_id__in=scope))
    return qs


def audit_for(actor):
    return AuditEvent.objects.all()
