"""Transactional PSM use cases. Cross-module identities are stored as scalar IDs."""

import re
import smtplib
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

from django.conf import settings
from django.core.mail import send_mail
from django.core.mail.message import BadHeaderError
from django.db import DatabaseError, transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone

from modules.directory import contracts as directory
from modules.psm.domain.workflow import IndentStatus, procurement_method, validate_transition
from modules.psm.models import (
    ApprovalDecision,
    AuditEvent,
    Bid,
    Communication,
    DiscrepancyCase,
    GoodsReceipt,
    GoodsReceiptLine,
    Indent,
    IndentLine,
    IndentVersion,
    InternalIssue,
    InventoryBalance,
    Invoice,
    Payment,
    Policy,
    PurchaseOrder,
    ReportRun,
    ReportSchedule,
    StockMovement,
    StockReservation,
    StockTransfer,
    StockTransferLine,
    Tender,
    Vendor,
    VendorVersion,
)


class PSMRuleError(ValueError):
    """A use-case precondition was not met."""


def _audit(actor_id, action, obj, **details):
    AuditEvent.objects.create(
        actor_id=actor_id,
        action=action,
        object_type=obj.__class__.__name__,
        object_id=obj.pk,
        details=details,
    )


def _snapshot(indent):
    lines = []
    for row in indent.lines.filter(active=True).values(
        "item_code", "description", "quantity", "estimated_unit_cost", "unit"
    ):
        lines.append({key: str(value) if isinstance(value, Decimal) else value
                      for key, value in row.items()})
    return {
        "status": indent.status,
        "department_id": indent.department_id,
        "justification": indent.justification,
        "priority": indent.priority,
        "criticality": indent.criticality,
        "lines": lines,
    }


def department_id_for_actor(actor):
    """Resolve a department from IAM identity data plus an institution mapping."""
    try:
        user = directory.get_users([actor.user_id]).get(actor.user_id)
    except (DatabaseError, IamUnavailable) as exc:
        raise PSMRuleError("The IAM directory is unavailable; department scope cannot be verified.") from exc
    if user is None or not user.department:
        raise PSMRuleError("Your department is missing from the IAM directory profile.")
    mapping = policy_value("department_id_by_name")
    if not isinstance(mapping, dict):
        raise PSMRuleError("Configure department_id_by_name before creating or reviewing indents.")
    department_id = mapping.get(user.department) or mapping.get(user.department.strip().lower())
    try:
        return int(department_id)
    except (TypeError, ValueError) as exc:
        raise PSMRuleError(
            "Your IAM department has no configured PSM department mapping."
        ) from exc


@transaction.atomic
def create_indent(
    *, actor, department_id=None, justification, lines, priority="", criticality="", source_indent=None
):
    if not justification.strip() or not lines:
        raise PSMRuleError("An indent needs item details and a justification.")
    department_id = department_id_for_actor(actor)
    if source_indent and source_indent.department_id != department_id:
        raise PSMRuleError("The repeated indent is outside your current IAM department.")
    indent = Indent.objects.create(
        indent_number=f"PSM-{timezone.now():%Y%m%d}-{uuid4().hex[:8].upper()}",
        requestor_id=actor.user_id,
        department_id=department_id,
        justification=justification.strip(),
        priority=priority,
        criticality=criticality,
        source_indent=source_indent,
    )
    total = Decimal("0")
    for item in lines:
        line = IndentLine.objects.create(indent=indent, **item)
        total += line.quantity * line.estimated_unit_cost
    indent.estimated_total = total
    indent.save(update_fields=("estimated_total", "updated_at"))
    IndentVersion.objects.create(
        indent=indent, version=1, snapshot=_snapshot(indent), changed_by_id=actor.user_id
    )
    _audit(actor.user_id, "indent.created", indent)
    return indent


@transaction.atomic
def submit_indent(*, indent, actor):
    validate_transition(indent.status, IndentStatus.SUBMITTED)
    lines = list(indent.lines.filter(active=True))
    if not lines or not indent.justification.strip():
        raise PSMRuleError("Add item details and a justification before submission.")
    # Exact active-content match is a review warning; it does not silently block a valid request.
    duplicate = (
        Indent.objects.filter(
            requestor_id=indent.requestor_id,
            department_id=indent.department_id,
            status__in=(
                "submitted",
                "department_review",
                "head_review",
                "procurement_review",
                "final_approval",
                "procurement_authorized",
                "tender",
            ),
        )
        .exclude(pk=indent.pk)
        .filter(justification=indent.justification)
        .exists()
    )
    indent.status = IndentStatus.SUBMITTED
    indent.submitted_at = timezone.now()
    indent.save(update_fields=("status", "submitted_at", "updated_at"))
    _audit(actor.user_id, "indent.submitted", indent, possible_duplicate=duplicate)
    Communication.objects.create(
        recipient_id=indent.requestor_id,
        event="indent.submitted",
        subject=f"Indent {indent.indent_number} submitted",
        body="Your purchase indent has been submitted for review.",
        reference_type="indent",
        reference_id=indent.pk,
    )
    return {"indent": indent, "possible_duplicate": duplicate}


@transaction.atomic
def modify_indent(*, indent, actor, data):
    if indent.requestor_id != actor.user_id:
        raise PSMRuleError("Only the requestor may modify this indent.")
    allowed = policy_value("modifiable_indent_states")
    if not isinstance(allowed, list) or indent.status not in allowed:
        raise PSMRuleError("Configure permissible modification states or use a draft indent.")
    if not data.get("justification", "").strip() or not data.get("lines"):
        raise PSMRuleError("An indent needs item details and a justification.")
    indent.justification = data["justification"].strip()
    indent.priority = data.get("priority", indent.priority)
    indent.criticality = data.get("criticality", indent.criticality)
    if department_id_for_actor(actor) != indent.department_id:
        raise PSMRuleError("Your IAM department no longer matches this indent.")
    for reservation in indent.reservations.filter(released_at__isnull=True):
        reservation.released_at = timezone.now()
        reservation.save(update_fields=("released_at", "updated_at"))
    indent.lines.filter(active=True).update(active=False)
    total = Decimal("0")
    for row in data["lines"]:
        line = IndentLine.objects.create(indent=indent, **row)
        total += line.quantity * line.estimated_unit_cost
    indent.estimated_total = total
    if indent.status != IndentStatus.DRAFT:
        indent.status = IndentStatus.DEPARTMENT_REVIEW
    indent.save()
    version = (
        indent.versions.order_by("-version").values_list("version", flat=True).first() or 0
    ) + 1
    IndentVersion.objects.create(
        indent=indent, version=version, snapshot=_snapshot(indent), changed_by_id=actor.user_id
    )
    _audit(actor.user_id, "indent.modified", indent, version=version)
    Communication.objects.create(
        recipient_id=indent.requestor_id,
        event="indent.modified",
        subject=f"Indent {indent.indent_number} updated",
        body="Your indent was saved and returned for review.",
        reference_type="indent",
        reference_id=indent.pk,
    )
    return indent


@transaction.atomic
def repeat_indent(*, indent, actor):
    if indent.requestor_id != actor.user_id:
        raise PSMRuleError("Only the requestor may repeat this indent.")
    return create_indent(
        actor=actor,
        department_id=indent.department_id,
        justification=indent.justification,
        priority=indent.priority,
        criticality=indent.criticality,
        source_indent=indent,
        lines=list(
            indent.lines.filter(active=True).values(
                "item_code", "description", "quantity", "estimated_unit_cost", "unit"
            )
        ),
    )


@transaction.atomic
def withdraw_indent(*, indent, actor):
    if indent.requestor_id != actor.user_id:
        raise PSMRuleError("Only the requestor may withdraw this indent.")
    allowed = policy_value("withdrawable_indent_states")
    if not isinstance(allowed, list) or indent.status not in allowed:
        raise PSMRuleError("Configure permissible withdrawal states for this indent.")
    for reservation in indent.reservations.filter(released_at__isnull=True):
        reservation.released_at = timezone.now()
        reservation.save(update_fields=("released_at", "updated_at"))
    indent.status = "withdrawn"
    indent.closed_at = timezone.now()
    indent.save(update_fields=("status", "closed_at", "updated_at"))
    _audit(actor.user_id, "indent.withdrawn", indent)
    return indent


@transaction.atomic
def cancel_indent(*, indent, actor):
    if indent.requestor_id != actor.user_id:
        raise PSMRuleError("Only the requestor may cancel this indent.")
    allowed = policy_value("cancellable_indent_states")
    if not isinstance(allowed, list) or indent.status not in allowed:
        raise PSMRuleError("Configure permissible cancellation states for this indent.")
    for reservation in indent.reservations.filter(released_at__isnull=True):
        reservation.released_at = timezone.now()
        reservation.save(update_fields=("released_at", "updated_at"))
    indent.status = "cancelled"
    indent.closed_at = timezone.now()
    indent.save(update_fields=("status", "closed_at", "updated_at"))
    _audit(actor.user_id, "indent.cancelled", indent)
    return indent


@transaction.atomic
def check_and_reserve_stock(*, indent, actor):
    """Reserve every line only when all required quantities are available."""
    if indent.status != IndentStatus.SUBMITTED:
        raise PSMRuleError("Stock can be checked only after an indent is submitted.")
    lines = list(indent.lines.filter(active=True))
    allocation = []
    for line in lines:
        balances = list(
            InventoryBalance.objects.select_for_update()
            .filter(item_code=line.item_code)
            .filter(Q(department_id=indent.department_id) | Q(department_id__isnull=True))
            .order_by("department_id", "id")
        )
        remaining = line.quantity
        for balance in balances:
            reserved = StockReservation.objects.filter(
                balance=balance, released_at__isnull=True
            ).aggregate(total=Sum("quantity"))["total"] or Decimal("0")
            transfer_reserved = StockTransferLine.objects.filter(
                source_balance=balance, transfer__status="requested"
            ).aggregate(total=Sum("quantity"))["total"] or Decimal("0")
            available = max(Decimal("0"), balance.quantity_on_hand - reserved - transfer_reserved)
            take = min(remaining, available)
            if take:
                allocation.append((line, balance, take))
                remaining -= take
            if remaining <= 0:
                break
        if remaining > 0:
            return {"reserved": False, "available": False}
    for line, balance, amount in allocation:
        StockReservation.objects.create(indent=indent, line=line, balance=balance, quantity=amount)
    indent.status = IndentStatus.STOCK_RESERVED
    indent.save(update_fields=("status", "updated_at"))
    _audit(actor.user_id, "stock.reserved", indent, reservation_count=len(allocation))
    return {"reserved": True, "available": True}


@transaction.atomic
def schedule_internal_issue(*, indent, actor, scheduled_for=None):
    if indent.status != IndentStatus.STOCK_RESERVED:
        raise PSMRuleError("Reserve sufficient stock before scheduling an internal issue.")
    reservations = list(indent.reservations.filter(released_at__isnull=True))
    if not reservations:
        raise PSMRuleError("This indent has no active stock reservation.")
    issue = InternalIssue.objects.create(indent=indent, scheduled_for=scheduled_for)
    indent.status = IndentStatus.INTERNAL_ISSUE
    indent.save(update_fields=("status", "updated_at"))
    _audit(actor.user_id, "internal_issue.scheduled", issue)
    return issue


@transaction.atomic
def dispatch_internal_issue(*, issue, actor):
    issue = InternalIssue.objects.select_for_update().get(pk=issue.pk)
    if issue.status != "scheduled":
        raise PSMRuleError("Only a scheduled internal issue can be dispatched.")
    issue.status = "dispatched"
    issue.dispatched_by_id = actor.user_id
    issue.dispatched_at = timezone.now()
    issue.save(update_fields=("status", "dispatched_by_id", "dispatched_at", "updated_at"))
    Communication.objects.create(
        recipient_id=issue.indent.requestor_id,
        event="internal_issue.dispatched",
        subject=f"Indent {issue.indent.indent_number} dispatched",
        body="Your reserved stock has been dispatched. Please confirm receipt.",
        reference_type="internal_issue",
        reference_id=issue.pk,
    )
    _audit(actor.user_id, "internal_issue.dispatched", issue)
    return issue


@transaction.atomic
def acknowledge_internal_receipt(*, issue, actor, discrepancy_notes=""):
    issue = InternalIssue.objects.select_for_update().select_related("indent").get(pk=issue.pk)
    if issue.status != "dispatched":
        raise PSMRuleError("Only a dispatched internal issue can be acknowledged.")
    if issue.indent.requestor_id != actor.user_id:
        raise PSMRuleError("Only the requestor can acknowledge delivery.")
    if discrepancy_notes.strip():
        issue.status = "discrepancy"
        issue.discrepancy_notes = discrepancy_notes.strip()
        issue.save(update_fields=("status", "discrepancy_notes", "updated_at"))
        _audit(actor.user_id, "internal_issue.discrepancy_reported", issue)
        return issue
    for reservation in issue.indent.reservations.select_related("balance"):
        if reservation.released_at:
            continue
        balance = InventoryBalance.objects.select_for_update().get(pk=reservation.balance_id)
        if balance.quantity_on_hand < reservation.quantity:
            raise PSMRuleError("Reserved inventory changed before delivery confirmation.")
        balance.quantity_on_hand -= reservation.quantity
        balance.save(update_fields=("quantity_on_hand", "updated_at"))
        reservation.released_at = timezone.now()
        reservation.save(update_fields=("released_at", "updated_at"))
        StockMovement.objects.create(
            item_code=reservation.line.item_code,
            location_id=balance.location_id,
            quantity_delta=-reservation.quantity,
            reference_type="internal_issue",
            reference_id=issue.pk,
            actor_id=actor.user_id,
        )
    issue.status = "received"
    issue.acknowledged_by_id = actor.user_id
    issue.acknowledged_at = timezone.now()
    issue.save(update_fields=("status", "acknowledged_by_id", "acknowledged_at", "updated_at"))
    issue.indent.status = IndentStatus.RECEIVED
    issue.indent.closed_at = timezone.now()
    issue.indent.save(update_fields=("status", "closed_at", "updated_at"))
    _audit(actor.user_id, "internal_issue.receipt_acknowledged", issue)
    return issue


@transaction.atomic
def resolve_internal_issue_discrepancy(*, issue, actor, resolution_notes):
    issue = InternalIssue.objects.select_for_update().get(pk=issue.pk)
    if issue.status != "discrepancy" or not resolution_notes.strip():
        raise PSMRuleError("An open internal-issue discrepancy and resolution notes are required.")
    issue.status = "dispatched"
    issue.discrepancy_notes = f"{issue.discrepancy_notes}\nResolution: {resolution_notes.strip()}"
    issue.save(update_fields=("status", "discrepancy_notes", "updated_at"))
    _audit(actor.user_id, "internal_issue.discrepancy_resolved", issue)
    return issue


@transaction.atomic
def decide_indent(*, indent, actor, decision, role, justification="", next_role=""):
    decision = decision.lower()
    if decision not in {"approve", "reject", "recommend"}:
        raise PSMRuleError("Decision must be approve, reject, or recommend.")
    target = IndentStatus.REJECTED if decision == "reject" else None
    if target:
        validate_transition(indent.status, target, reason=justification)
    elif decision in {"recommend", "approve"} and indent.status == IndentStatus.DEPARTMENT_REVIEW:
        hierarchy = policy_value("approval_hierarchy")
        if not isinstance(hierarchy, dict) or "department_head_required" not in hierarchy:
            raise PSMRuleError("Configure approval_hierarchy before routing indent approvals.")
        target = (
            IndentStatus.HEAD_REVIEW
            if hierarchy["department_head_required"]
            else IndentStatus.PROCUREMENT_REVIEW
        )
    elif decision == "approve" and indent.status == IndentStatus.HEAD_REVIEW:
        target = IndentStatus.PROCUREMENT_REVIEW
    elif decision == "approve" and indent.status == IndentStatus.PROCUREMENT_REVIEW:
        hierarchy = policy_value("approval_hierarchy")
        threshold = (
            hierarchy.get("final_approval_threshold") if isinstance(hierarchy, dict) else None
        )
        if threshold is None:
            raise PSMRuleError("Configure the final approval threshold before procurement routing.")
        indent.selected_procurement_method = select_procurement_method(indent.estimated_total)
        target = (
            IndentStatus.FINAL_APPROVAL
            if indent.estimated_total >= Decimal(str(threshold))
            else IndentStatus.PROCUREMENT_AUTHORIZED
        )
    elif decision == "approve" and indent.status == IndentStatus.FINAL_APPROVAL:
        target = IndentStatus.PROCUREMENT_AUTHORIZED
    else:
        raise PSMRuleError(f"Decision is not valid while indent is {indent.status}.")
    validate_transition(indent.status, target, reason=justification)
    ApprovalDecision.objects.create(
        indent=indent,
        actor_id=actor.user_id,
        role=role,
        decision=decision,
        justification=justification.strip(),
    )
    indent.status = target
    indent.current_approver_role = (
        "department_head"
        if target == IndentStatus.HEAD_REVIEW
        else "director_or_registrar"
        if target == IndentStatus.FINAL_APPROVAL
        else ""
    )
    indent.save(
        update_fields=(
            "status",
            "current_approver_role",
            "selected_procurement_method",
            "updated_at",
        )
    )
    _audit(
        actor.user_id,
        f"indent.{decision}",
        indent,
        role=role,
        justification=justification,
        resulting_status=target,
    )
    if decision == "reject":
        Communication.objects.create(
            recipient_id=indent.requestor_id,
            event="indent.rejected",
            subject=f"Indent {indent.indent_number} rejected",
            body=justification,
            reference_type="indent",
            reference_id=indent.pk,
        )
    return indent


@transaction.atomic
def issue_purchase_order(*, indent, vendor, actor, total_amount, planned_delivery_at=None):
    tender_awarded = (
        indent.status == IndentStatus.TENDER
        and hasattr(indent, "tender")
        and indent.tender.status == "awarded"
    )
    if indent.status != IndentStatus.PROCUREMENT_AUTHORIZED and not tender_awarded:
        raise PSMRuleError("Required approvals must be complete before issuing a purchase order.")
    if tender_awarded and indent.tender.selected_bid.vendor_id != vendor.pk:
        raise PSMRuleError(
            "The purchase order vendor must be the committee-selected tender vendor."
        )
    if (
        indent.status == IndentStatus.PROCUREMENT_AUTHORIZED
        and indent.selected_procurement_method != "direct"
    ):
        raise PSMRuleError(
            "The configured procurement method does not permit a direct purchase order."
        )
    if not vendor.active or not vendor.verified or not vendor.gst_number or not vendor.bank_details:
        raise PSMRuleError("A verified vendor with required tax and bank details is required.")
    po = PurchaseOrder.objects.create(
        indent=indent,
        vendor=vendor,
        po_number=f"PO-{timezone.now():%Y%m%d}-{uuid4().hex[:8].upper()}",
        total_amount=total_amount,
        planned_delivery_at=planned_delivery_at,
        issued_by_id=actor.user_id,
    )
    indent.status = IndentStatus.PO_ISSUED
    indent.save(update_fields=("status", "updated_at"))
    _audit(actor.user_id, "purchase_order.issued", po, indent_id=indent.pk, vendor_id=vendor.pk)
    Communication.objects.create(
        recipient_id=indent.requestor_id,
        event="purchase_order.issued",
        subject=f"Purchase order issued for {indent.indent_number}",
        body=f"Purchase order {po.po_number} has been issued.",
        reference_type="purchase_order",
        reference_id=po.pk,
    )
    if vendor.contact_email:
        Communication.objects.create(
            recipient_email=vendor.contact_email,
            event="purchase_order.issued",
            subject=f"Purchase order {po.po_number}",
            body="A purchase order has been issued to your organization.",
            reference_type="purchase_order",
            reference_id=po.pk,
        )
    return po


@transaction.atomic
def record_receipt(*, purchase_order, actor, lines, evidence=None):
    if not lines:
        raise PSMRuleError("At least one received purchase-order line is required.")
    expected = {
        row.pk: row for row in purchase_order.indent.lines.select_for_update().filter(active=True)
    }
    previously_received = {}
    for prior in purchase_order.receipts.select_for_update().prefetch_related("lines"):
        for prior_line in prior.lines.all():
            previously_received[prior_line.indent_line_id] = (
                previously_received.get(prior_line.indent_line_id, Decimal("0"))
                + prior_line.accepted_quantity
            )
    receipt = GoodsReceipt.objects.create(
        purchase_order=purchase_order,
        grn_number=f"GRN-{timezone.now():%Y%m%d}-{uuid4().hex[:8].upper()}",
        inspected_by_id=actor.user_id,
        evidence=evidence or [],
    )
    has_discrepancy = False
    seen = set()
    for row in lines:
        line_id = int(row["indent_line_id"])
        if line_id not in expected or line_id in seen:
            raise PSMRuleError("Each receipt line must refer once to an item on this indent.")
        seen.add(line_id)
        accepted = Decimal(row.get("accepted_quantity", 0))
        rejected = Decimal(row.get("rejected_quantity", 0))
        if accepted < 0 or rejected < 0:
            raise PSMRuleError("Receipt quantities cannot be negative.")
        remaining = expected[line_id].quantity - previously_received.get(line_id, Decimal("0"))
        if accepted + rejected > remaining:
            raise PSMRuleError(
                "Received and rejected quantities exceed the outstanding order quantity."
            )
        GoodsReceiptLine.objects.create(
            receipt=receipt,
            indent_line_id=line_id,
            accepted_quantity=accepted,
            rejected_quantity=rejected,
            notes=row.get("notes", ""),
        )
        has_discrepancy |= rejected > 0 or bool(row.get("notes"))
    receipt.discrepancy_open = has_discrepancy
    receipt.status = "discrepancy" if has_discrepancy else "awaiting_confirmation"
    receipt.save(update_fields=("discrepancy_open", "status", "updated_at"))
    if has_discrepancy:
        reasons = [line.notes for line in receipt.lines.all() if line.notes]
        rejected = sum((line.rejected_quantity for line in receipt.lines.all()), Decimal("0"))
        DiscrepancyCase.objects.create(
            receipt=receipt,
            opened_by_id=actor.user_id,
            description="; ".join(reasons) or f"{rejected} units were rejected during inspection.",
            evidence=evidence or [],
        )
    _audit(actor.user_id, "goods_receipt.recorded", receipt, discrepancy_open=has_discrepancy)
    return receipt


@transaction.atomic
def confirm_receipt(*, receipt, actor, destination_location_id):
    receipt = GoodsReceipt.objects.select_for_update().get(pk=receipt.pk)
    if receipt.purchase_order.indent.requestor_id != actor.user_id:
        raise PSMRuleError("Only the indent requestor may confirm the goods receipt.")
    if receipt.discrepancy_open or receipt.cases.filter(status="open").exists():
        raise PSMRuleError("Resolve open delivery discrepancies before confirming receipt.")
    if receipt.confirmed_at:
        raise PSMRuleError("This goods receipt was already confirmed.")
    for line in receipt.lines.select_related("indent_line"):
        if line.accepted_quantity <= 0:
            continue
        item_code = line.indent_line.item_code
        balance, _ = InventoryBalance.objects.select_for_update().get_or_create(
            item_code=item_code,
            location_id=destination_location_id,
            department_id=receipt.purchase_order.indent.department_id,
            defaults={"description": line.indent_line.description},
        )
        balance.quantity_on_hand += line.accepted_quantity
        balance.save(update_fields=("quantity_on_hand", "updated_at"))
        StockMovement.objects.create(
            item_code=item_code,
            location_id=destination_location_id,
            quantity_delta=line.accepted_quantity,
            reference_type="goods_receipt",
            reference_id=receipt.pk,
            actor_id=actor.user_id,
        )
    receipt.confirmed_by_id = actor.user_id
    receipt.confirmed_at = timezone.now()
    receipt.status = "confirmed"
    receipt.save(update_fields=("confirmed_by_id", "confirmed_at", "status", "updated_at"))
    po = receipt.purchase_order
    received = {}
    for prior in po.receipts.prefetch_related("lines"):
        for row in prior.lines.all():
            received[row.indent_line_id] = (
                received.get(row.indent_line_id, Decimal("0")) + row.accepted_quantity
            )
    complete = all(
        received.get(line.pk, Decimal("0")) >= line.quantity
        for line in po.indent.lines.filter(active=True)
    )
    po.actual_delivery_at = receipt.confirmed_at
    po.status = "received" if complete else "partially_received"
    po.save(update_fields=("actual_delivery_at", "status", "updated_at"))
    indent = po.indent
    indent.status = IndentStatus.RECEIVED if complete else IndentStatus.PARTIALLY_RECEIVED
    if complete:
        indent.closed_at = timezone.now()
    indent.save(update_fields=("status", "closed_at", "updated_at"))
    _audit(actor.user_id, "goods_receipt.confirmed", receipt)
    Communication.objects.create(
        recipient_id=po.indent.requestor_id,
        event="goods_receipt.confirmed",
        subject=f"Receipt confirmed for {po.indent.indent_number}",
        body=f"Goods receipt {receipt.grn_number} was confirmed.",
        reference_type="goods_receipt",
        reference_id=receipt.pk,
    )
    return receipt


@transaction.atomic
def verify_invoice(*, invoice, actor):
    invoice = (
        Invoice.objects.select_for_update()
        .select_related("purchase_order__vendor")
        .get(pk=invoice.pk)
    )
    receipts = invoice.purchase_order.receipts.filter(
        confirmed_at__isnull=False, discrepancy_open=False
    )
    accepted = sum(
        (
            line.accepted_quantity * line.indent_line.estimated_unit_cost
            for receipt in receipts
            for line in receipt.lines.select_related("indent_line")
        ),
        Decimal("0"),
    )
    if (
        not invoice.purchase_order.vendor.verified
        or accepted == 0
        or invoice.invoice_amount > accepted
        or invoice.invoice_amount > invoice.purchase_order.total_amount
    ):
        invoice.status = "held"
    else:
        invoice.status = "verified"
        invoice.matched_amount = invoice.invoice_amount
        invoice.verified_by_id = actor.user_id
        invoice.verified_at = timezone.now()
    invoice.save(
        update_fields=("status", "matched_amount", "verified_by_id", "verified_at", "updated_at")
    )
    _audit(
        actor.user_id,
        "invoice.verified" if invoice.status == "verified" else "invoice.held",
        invoice,
        accepted_value=str(accepted),
    )
    Communication.objects.create(
        recipient_id=invoice.purchase_order.indent.requestor_id,
        event=f"invoice.{invoice.status}",
        subject=f"Invoice {invoice.vendor_invoice_number} {invoice.status}",
        body=(
            "The invoice passed three-way verification."
            if invoice.status == "verified"
            else "The invoice is on hold pending procurement and receipt review."
        ),
        reference_type="invoice",
        reference_id=invoice.pk,
    )
    return invoice


@transaction.atomic
def process_payment(*, invoice, actor, amount, reference=""):
    invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
    if invoice.status != "verified":
        raise PSMRuleError("Payment requires a verified, matched invoice.")
    paid = invoice.payments.aggregate(total=Sum("amount"))["total"] or Decimal("0")
    remaining = invoice.matched_amount - paid
    amount = Decimal(amount)
    if amount <= 0 or amount > remaining:
        raise PSMRuleError("Payment must be positive and cannot exceed the verified balance.")
    payment = Payment.objects.create(
        invoice=invoice, amount=amount, reference=reference, processed_by_id=actor.user_id
    )
    if amount == remaining:
        invoice.status = "paid"
        invoice.save(update_fields=("status", "updated_at"))
    _audit(actor.user_id, "payment.processed", payment, invoice_id=invoice.pk)
    vendor = invoice.purchase_order.vendor
    if vendor.contact_email:
        Communication.objects.create(
            recipient_email=vendor.contact_email,
            event="payment.processed",
            subject=f"Payment processed for invoice {invoice.vendor_invoice_number}",
            body=f"A payment of {amount} was processed. Reference: {reference or 'not provided'}.",
            reference_type="payment",
            reference_id=payment.pk,
        )
    return payment


@transaction.atomic
def save_vendor(*, actor, data, vendor=None):
    if vendor is None:
        vendor = Vendor.objects.create(created_by_id=actor.user_id, **data)
        version = 1
        action = "vendor.created"
    else:
        vendor = Vendor.objects.select_for_update().get(pk=vendor.pk)
        version = (
            vendor.versions.order_by("-version").values_list("version", flat=True).first() or 0
        ) + 1
        for key, value in data.items():
            setattr(vendor, key, value)
        # Any master-data change requires re-verification.
        vendor.verified = False
        vendor.save()
        action = "vendor.updated"
    snapshot = {
        "name": vendor.name,
        "gst_number": vendor.gst_number,
        "bank_details": vendor.bank_details,
        "compliance_documents": vendor.compliance_documents,
        "verified": vendor.verified,
    }
    VendorVersion.objects.create(
        vendor=vendor, version=version, snapshot=snapshot, changed_by_id=actor.user_id
    )
    _audit(actor.user_id, action, vendor, version=version)
    return vendor


@transaction.atomic
def verify_vendor(*, vendor, actor):
    vendor = Vendor.objects.select_for_update().get(pk=vendor.pk)
    if not re.fullmatch(
        r"[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]",
        vendor.gst_number.upper(),
    ):
        raise PSMRuleError("Enter a GSTIN in the expected 15-character format.")
    bank = vendor.bank_details
    if not isinstance(bank, dict) or not all(
        str(bank.get(key, "")).strip() for key in ("bank_name", "account_number", "ifsc")
    ):
        raise PSMRuleError("Bank name, account number, and IFSC are required.")
    if not re.fullmatch(r"[A-Z]{4}0[A-Z0-9]{6}", str(bank["ifsc"]).upper()):
        raise PSMRuleError("Enter an IFSC in the expected 11-character format.")
    docs = vendor.compliance_documents
    if (
        not isinstance(docs, list)
        or not docs
        or any(
            not isinstance(doc, dict) or not doc.get("type") or not doc.get("reference")
            for doc in docs
        )
    ):
        raise PSMRuleError("Add each compliance document with its type and reference.")
    required = policy_value("required_vendor_documents", [])
    supplied = {str(doc["type"]) for doc in docs}
    missing = set(required or []) - supplied
    if missing:
        raise PSMRuleError(f"Required vendor documents are missing: {', '.join(sorted(missing))}.")
    vendor.verified = True
    vendor.save(update_fields=("verified", "updated_at"))
    version = (
        vendor.versions.order_by("-version").values_list("version", flat=True).first() or 0
    ) + 1
    VendorVersion.objects.create(
        vendor=vendor,
        version=version,
        snapshot={
            "name": vendor.name,
            "gst_number": vendor.gst_number,
            "bank_details": vendor.bank_details,
            "compliance_documents": vendor.compliance_documents,
            "verified": True,
        },
        changed_by_id=actor.user_id,
    )
    _audit(actor.user_id, "vendor.verified", vendor, version=version)
    return vendor


def policy_value(key, default=None):
    row = Policy.objects.filter(key=key, active=True).first()
    return row.value if row else default


def select_procurement_method(amount):
    raw = policy_value("tender_threshold")
    threshold = Decimal(str(raw)) if raw is not None else None
    return procurement_method(Decimal(amount), tender_threshold=threshold)


def report_snapshot(report, filters=None):
    filters = filters or {}
    if report not in {"operations", "stock", "procurement", "financial"}:
        raise PSMRuleError("Choose an available PSM report.")
    indents = Indent.objects.all()
    if filters.get("indent_status"):
        indents = indents.filter(status=filters["indent_status"])
    if filters.get("department_id"):
        indents = indents.filter(department_id=filters["department_id"])
    if report == "operations":
        return {
            "indents_by_status": list(indents.values("status").annotate(count=Count("id"))),
            "indents": indents.count(),
            "estimated_total": str(indents.aggregate(total=Sum("estimated_total"))["total"] or 0),
        }
    if report == "stock":
        return {
            "items": InventoryBalance.objects.count(),
            "quantity_on_hand": str(
                InventoryBalance.objects.aggregate(total=Sum("quantity_on_hand"))["total"] or 0
            ),
            "active_reservations": StockReservation.objects.filter(
                released_at__isnull=True
            ).count(),
            "transfers_by_status": list(
                StockTransfer.objects.values("status").annotate(count=Count("id"))
            ),
        }
    if report == "procurement":
        orders = PurchaseOrder.objects.all()
        if filters.get("department_id"):
            orders = orders.filter(indent__department_id=filters["department_id"])
        return {
            "orders_by_status": list(orders.values("status").annotate(count=Count("id"))),
            "order_value": str(orders.aggregate(total=Sum("total_amount"))["total"] or 0),
            "vendors_verified": Vendor.objects.filter(verified=True, active=True).count(),
            "open_tenders": Tender.objects.filter(
                status__in=("draft", "published", "evaluation")
            ).count(),
        }
    invoices = Invoice.objects.all()
    if filters.get("department_id"):
        invoices = invoices.filter(purchase_order__indent__department_id=filters["department_id"])
    return {
        "invoices_by_status": list(invoices.values("status").annotate(count=Count("id"))),
        "invoice_value": str(invoices.aggregate(total=Sum("invoice_amount"))["total"] or 0),
        "paid_value": str(
            Payment.objects.filter(invoice__in=invoices).aggregate(total=Sum("amount"))["total"]
            or 0
        ),
    }


@transaction.atomic
def run_scheduled_reports(*, now=None):
    now = now or timezone.now()
    schedules = ReportSchedule.objects.select_for_update().filter(active=True, next_run_at__lte=now)
    completed = 0
    for schedule in schedules:
        result = report_snapshot(schedule.report, schedule.filters)
        run = ReportRun.objects.create(
            report=schedule.report,
            requested_by_id=schedule.created_by_id,
            filters=schedule.filters,
            output_format="json",
            result=result,
        )
        schedule.last_run_at = now
        schedule.next_run_at = now + timedelta(seconds=schedule.interval_seconds)
        schedule.save(update_fields=("last_run_at", "next_run_at", "updated_at"))
        _audit(schedule.created_by_id, "report.generated", run, scheduled=True)
        completed += 1
    return completed


def deliver_communications(*, limit=100):
    """Drain the PSM mail outbox; delivery history remains on each communication."""
    stale_before = timezone.now() - timedelta(minutes=10)
    Communication.objects.filter(delivery_status="sending", updated_at__lt=stale_before).update(
        delivery_status="pending"
    )
    maximum_attempts = getattr(settings, "NOTIFY_MAX_ATTEMPTS", 5)
    ids = list(
        Communication.objects.filter(delivery_status="pending")
        .order_by("created_at")
        .values_list("pk", flat=True)[:limit]
    )
    sent = 0
    for message_id in ids:
        with transaction.atomic():
            message = Communication.objects.select_for_update().get(pk=message_id)
            if message.delivery_status != "pending":
                continue
            if message.delivery_attempts >= maximum_attempts:
                message.delivery_status = "failed"
                message.last_error = "Maximum delivery attempts reached."
                message.save(update_fields=("delivery_status", "last_error"))
                continue
            message.delivery_attempts += 1
            message.delivery_status = "sending"
            message.save(update_fields=("delivery_attempts", "delivery_status", "updated_at"))
            recipient = message.recipient_email
            recipient_id = message.recipient_id
            subject, body = message.subject, message.body
            attempts = message.delivery_attempts
        error = ""
        if not recipient and recipient_id:
            try:
                user = directory.get_users([recipient_id]).get(recipient_id)
                recipient = user.email if user else ""
            except (DatabaseError, IamUnavailable) as exc:
                error = str(exc)[:500]
        if not error and not recipient:
            error = "No recipient email address is available."
        if not error:
            try:
                delivered = send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [recipient])
                if not delivered:
                    error = "The configured email backend did not accept the message."
            except (BadHeaderError, OSError, smtplib.SMTPException) as exc:
                error = str(exc)[:500]
        with transaction.atomic():
            message = Communication.objects.select_for_update().get(pk=message_id)
            if error:
                message.delivery_status = "failed" if attempts >= maximum_attempts else "pending"
                message.last_error = error
                message.save(update_fields=("delivery_status", "last_error", "updated_at"))
                continue
            message.delivery_status = "sent"
            message.delivered_at = timezone.now()
            message.last_error = ""
            message.save(
                update_fields=("delivery_status", "delivered_at", "last_error", "updated_at")
            )
            sent += 1
    return sent


@transaction.atomic
def create_tender(*, indent, actor, closes_at=None, criteria=None):
    if indent.status != IndentStatus.PROCUREMENT_AUTHORIZED:
        raise PSMRuleError("A tender can be created only for authorized procurement.")
    if indent.selected_procurement_method != "tender":
        raise PSMRuleError("Configured policy selects direct procurement for this indent.")
    tender = Tender.objects.create(
        indent=indent,
        tender_number=f"TND-{timezone.now():%Y%m%d}-{uuid4().hex[:8].upper()}",
        closes_at=closes_at,
        evaluation_criteria=criteria or [],
        status="draft",
    )
    indent.status = IndentStatus.TENDER
    indent.save(update_fields=("status", "updated_at"))
    _audit(actor.user_id, "tender.created", tender, indent_id=indent.pk)
    return tender


@transaction.atomic
def publish_tender(*, tender, actor):
    tender = Tender.objects.select_for_update().get(pk=tender.pk)
    if tender.status != "draft":
        raise PSMRuleError("Only a draft tender can be published.")
    tender.status = "published"
    tender.published_at = timezone.now()
    tender.save(update_fields=("status", "published_at", "updated_at"))
    _audit(actor.user_id, "tender.published", tender)
    return tender


@transaction.atomic
def submit_bid(*, tender, vendor, actor, amount, submission):
    tender = Tender.objects.select_for_update().get(pk=tender.pk)
    if tender.status != "published" or (tender.closes_at and tender.closes_at < timezone.now()):
        raise PSMRuleError("This tender is not accepting bids.")
    bid = Bid.objects.create(tender=tender, vendor=vendor, amount=amount, submission=submission)
    _audit(actor.user_id, "tender.bid_received", bid, tender_id=tender.pk, vendor_id=vendor.pk)
    return bid


@transaction.atomic
def award_tender(*, tender, bid, actor, evaluation):
    tender = Tender.objects.select_for_update().get(pk=tender.pk)
    if tender.status not in {"published", "evaluation"} or bid.tender_id != tender.pk:
        raise PSMRuleError("Tender selection must reference a bid for an open tender.")
    if not tender.evaluation_criteria:
        raise PSMRuleError("Tender evaluation criteria must be recorded before selection.")
    bid.evaluation = evaluation
    bid.status = "selected"
    bid.save(update_fields=("evaluation", "status", "updated_at"))
    tender.selected_bid = bid
    tender.status = "awarded"
    tender.approved_by_id = actor.user_id
    tender.save(update_fields=("selected_bid", "status", "approved_by_id", "updated_at"))
    for other in tender.bids.exclude(pk=bid.pk):
        other.status = "not_selected"
        other.save(update_fields=("status", "updated_at"))
    _audit(actor.user_id, "tender.awarded", tender, selected_bid_id=bid.pk, evaluation=evaluation)
    return tender


@transaction.atomic
def open_discrepancy(*, receipt, actor, description, evidence=None):
    if receipt.confirmed_at:
        raise PSMRuleError("A confirmed receipt cannot open a new discrepancy case.")
    case = DiscrepancyCase.objects.create(
        receipt=receipt,
        opened_by_id=actor.user_id,
        description=description,
        evidence=evidence or [],
    )
    receipt.discrepancy_open = True
    receipt.status = "discrepancy"
    receipt.save(update_fields=("discrepancy_open", "status", "updated_at"))
    _audit(actor.user_id, "discrepancy.opened", case, receipt_id=receipt.pk)
    return case


@transaction.atomic
def resolve_discrepancy(*, case, actor, resolution, notes):
    case = DiscrepancyCase.objects.select_for_update().select_related("receipt").get(pk=case.pk)
    if case.status != "open":
        raise PSMRuleError("This discrepancy case has already been resolved.")
    if resolution not in {"return", "replacement", "warranty", "adjustment"} or not notes.strip():
        raise PSMRuleError("Choose a supported resolution and record resolution notes.")
    case.status = "resolved"
    case.resolution = resolution
    case.resolution_notes = notes.strip()
    case.save(update_fields=("status", "resolution", "resolution_notes", "updated_at"))
    receipt = case.receipt
    receipt.discrepancy_open = receipt.cases.filter(status="open").exclude(pk=case.pk).exists()
    receipt.status = "discrepancy" if receipt.discrepancy_open else "awaiting_confirmation"
    receipt.save(update_fields=("discrepancy_open", "status", "updated_at"))
    _audit(actor.user_id, "discrepancy.resolved", case, resolution=resolution)
    return case


@transaction.atomic
def request_stock_transfer(*, actor, source_department_id, destination_department_id, lines):
    if source_department_id == destination_department_id or not lines:
        raise PSMRuleError("Choose different source and destination departments and add items.")
    transfer = StockTransfer.objects.create(
        requested_by_id=actor.user_id,
        source_department_id=source_department_id,
        destination_department_id=destination_department_id,
    )
    for item in lines:
        quantity = Decimal(item["quantity"])
        if quantity <= 0:
            raise PSMRuleError("Transfer quantities must be greater than zero.")
        balance = (
            InventoryBalance.objects.select_for_update()
            .filter(item_code=item["item_code"], department_id=source_department_id)
            .first()
        )
        if balance is None:
            raise PSMRuleError(f"No source stock is recorded for {item['item_code']}.")
        reserved_indent = StockReservation.objects.filter(
            balance=balance, released_at__isnull=True
        ).aggregate(total=Sum("quantity"))["total"] or Decimal("0")
        reserved_transfer = StockTransferLine.objects.filter(
            source_balance=balance, transfer__status="requested"
        ).aggregate(total=Sum("quantity"))["total"] or Decimal("0")
        if balance.quantity_on_hand - reserved_indent - reserved_transfer < quantity:
            raise PSMRuleError(f"Insufficient unreserved stock for {item['item_code']}.")
        StockTransferLine.objects.create(
            transfer=transfer,
            item_code=item["item_code"],
            quantity=quantity,
            source_balance=balance,
        )
    _audit(actor.user_id, "stock_transfer.requested", transfer)
    return transfer


@transaction.atomic
def dispatch_stock_transfer(*, transfer, actor):
    transfer = StockTransfer.objects.select_for_update().get(pk=transfer.pk)
    if transfer.source_department_id != department_id_for_actor(actor):
        raise PSMRuleError("Only the source department may dispatch this transfer.")
    if transfer.status != "requested":
        raise PSMRuleError("Only a requested stock transfer can be dispatched.")
    for line in transfer.lines.select_related("source_balance"):
        balance = InventoryBalance.objects.select_for_update().get(pk=line.source_balance_id)
        balance.quantity_on_hand -= line.quantity
        balance.save(update_fields=("quantity_on_hand", "updated_at"))
        StockMovement.objects.create(
            item_code=line.item_code,
            location_id=balance.location_id,
            quantity_delta=-line.quantity,
            reference_type="stock_transfer",
            reference_id=transfer.pk,
            actor_id=actor.user_id,
        )
    transfer.status = "dispatched"
    transfer.dispatched_at = timezone.now()
    transfer.save(update_fields=("status", "dispatched_at", "updated_at"))
    _audit(actor.user_id, "stock_transfer.dispatched", transfer)
    return transfer


@transaction.atomic
def confirm_stock_transfer(*, transfer, actor, destination_location_id):
    transfer = StockTransfer.objects.select_for_update().get(pk=transfer.pk)
    if transfer.destination_department_id != department_id_for_actor(actor):
        raise PSMRuleError("Only the destination department may receive this transfer.")
    if transfer.status != "dispatched":
        raise PSMRuleError("Only a dispatched transfer can be received.")
    for line in transfer.lines.all():
        balance, _ = InventoryBalance.objects.select_for_update().get_or_create(
            item_code=line.item_code,
            location_id=destination_location_id,
            department_id=transfer.destination_department_id,
        )
        balance.quantity_on_hand += line.quantity
        balance.save(update_fields=("quantity_on_hand", "updated_at"))
        StockMovement.objects.create(
            item_code=line.item_code,
            location_id=destination_location_id,
            quantity_delta=line.quantity,
            reference_type="stock_transfer",
            reference_id=transfer.pk,
            actor_id=actor.user_id,
        )
    transfer.status = "completed"
    transfer.received_at = timezone.now()
    transfer.save(update_fields=("status", "received_at", "updated_at"))
    _audit(actor.user_id, "stock_transfer.completed", transfer)
    return transfer
