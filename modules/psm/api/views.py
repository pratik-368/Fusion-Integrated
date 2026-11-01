import csv

from django.db.models import Count, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from core.api.exceptions import ConflictError
from fusion_auth.permissions import HasModuleGrant, HasPermission
from modules.psm.api import serializers as s
from modules.psm.models import (
    ApprovalDecision,
    AuditEvent,
    Bid,
    Communication,
    DiscrepancyCase,
    GoodsReceipt,
    Indent,
    IndentVersion,
    InternalIssue,
    InventoryBalance,
    Invoice,
    Policy,
    PurchaseOrder,
    ReportRun,
    ReportSchedule,
    StockTransfer,
    Tender,
    Vendor,
)
from modules.psm.selectors import queries
from modules.psm.services import workflow as svc

MODULE = HasModuleGrant("psm")


def actor(request):
    return request.principal


def run_rule(call, *args, **kwargs):
    try:
        return call(*args, **kwargs)
    except svc.PSMRuleError as exc:
        raise ConflictError(str(exc), code="psm_rule_violation") from exc
    except ValueError as exc:
        raise ValidationError({"detail": str(exc)}) from exc


class IndentCollectionView(APIView):
    serializer_class = s.IndentReadSerializer
    permission_classes = [MODULE]

    def get_permissions(self):
        code = (
            ("psm.indent.view", "psm.indent.view_self")
            if self.request.method == "GET"
            else ("psm.indent.create",)
        )
        return [MODULE, HasPermission(*code)]

    def get(self, request):
        own = request.query_params.get("scope") == "mine" or not actor(request).has_permission(
            "psm.indent.view"
        )
        rows = queries.indents_for(actor(request), own=own).prefetch_related("lines")
        if request.query_params.get("status"):
            rows = rows.filter(status=request.query_params["status"])
        return Response(s.IndentReadSerializer(rows[:100], many=True).data)

    def post(self, request):
        payload = s.IndentCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        indent = run_rule(svc.create_indent, actor=actor(request), **data)
        return Response(s.IndentReadSerializer(indent).data, status=status.HTTP_201_CREATED)


class IndentActionView(APIView):
    serializer_class = s.IndentReadSerializer
    permission_classes = [MODULE]
    action_permissions = {
        "submit": "psm.indent.create",
        "stock-check": "psm.stock.manage",
        "decision": "psm.indent.review",
        "withdraw": "psm.indent.withdraw",
        "cancel": "psm.indent.withdraw",
        "modify": "psm.indent.create",
        "repeat": "psm.indent.create",
        "internal-issue": "psm.stock.manage",
        "dispatch-internal": "psm.stock.manage",
        "acknowledge-receipt": "psm.indent.create",
        "resolve-internal-discrepancy": "psm.receipt.manage",
    }

    @extend_schema(operation_id="psm_indent_action")
    def post(self, request, pk, action):
        if action not in self.action_permissions:
            return Response({"detail": "Unknown indent action."}, status=404)
        if not actor(request).has_permission(self.action_permissions[action]):
            raise PermissionDenied
        indent = get_object_or_404(queries.indents_for(actor(request)), pk=pk)
        if action == "submit":
            result = run_rule(svc.submit_indent, indent=indent, actor=actor(request))
            return Response(
                {
                    **s.IndentReadSerializer(result["indent"]).data,
                    "possible_duplicate": result["possible_duplicate"],
                }
            )
        if action == "stock-check":
            result = run_rule(svc.check_and_reserve_stock, indent=indent, actor=actor(request))
            if not result["available"]:
                indent.status = "department_review"
                indent.save(update_fields=("status", "updated_at"))
                AuditEvent.objects.create(
                    actor_id=actor(request).user_id,
                    action="stock.insufficient",
                    object_type="Indent",
                    object_id=indent.pk,
                    details={"external_procurement_required": True},
                )
            return Response({**result, "indent": s.IndentReadSerializer(indent).data})
        if action == "decision":
            data = request.data
            indent = run_rule(
                svc.decide_indent,
                indent=indent,
                actor=actor(request),
                decision=data.get("decision", ""),
                role=actor(request).active_role or "",
                justification=data.get("justification", ""),
                next_role=data.get("next_role", ""),
            )
            return Response(s.IndentReadSerializer(indent).data)
        if action == "modify":
            payload = s.IndentCreateSerializer(data=request.data)
            payload.is_valid(raise_exception=True)
            indent = run_rule(
                svc.modify_indent,
                indent=indent,
                actor=actor(request),
                data=payload.validated_data,
            )
            return Response(s.IndentReadSerializer(indent).data)
        if action == "repeat":
            repeated = run_rule(svc.repeat_indent, indent=indent, actor=actor(request))
            return Response(s.IndentReadSerializer(repeated).data, status=201)
        if action == "cancel":
            indent = run_rule(svc.cancel_indent, indent=indent, actor=actor(request))
            return Response(s.IndentReadSerializer(indent).data)
        if action == "internal-issue":
            issue = run_rule(
                svc.schedule_internal_issue,
                indent=indent,
                actor=actor(request),
                scheduled_for=request.data.get("scheduled_for"),
            )
            return Response({"id": issue.pk, "status": issue.status}, status=201)
        if action == "dispatch-internal":
            issue = get_object_or_404(InternalIssue, indent=indent)
            issue = run_rule(svc.dispatch_internal_issue, issue=issue, actor=actor(request))
            return Response({"id": issue.pk, "status": issue.status})
        if action == "acknowledge-receipt":
            if indent.requestor_id != actor(request).user_id:
                raise PermissionDenied
            issue = get_object_or_404(InternalIssue, indent=indent)
            issue = run_rule(
                svc.acknowledge_internal_receipt,
                issue=issue,
                actor=actor(request),
                discrepancy_notes=request.data.get("discrepancy_notes", ""),
            )
            return Response({"id": issue.pk, "status": issue.status})
        if action == "resolve-internal-discrepancy":
            issue = get_object_or_404(InternalIssue, indent=indent)
            issue = run_rule(
                svc.resolve_internal_issue_discrepancy,
                issue=issue,
                actor=actor(request),
                resolution_notes=request.data.get("resolution_notes", ""),
            )
            return Response({"id": issue.pk, "status": issue.status})
        if indent.requestor_id != actor(request).user_id:
            raise PermissionDenied
        indent = run_rule(svc.withdraw_indent, indent=indent, actor=actor(request))
        return Response(s.IndentReadSerializer(indent).data)


class IndentHistoryView(APIView):
    serializer_class = s.IndentHistorySerializer
    permission_classes = [MODULE]

    def get_permissions(self):
        return [MODULE, HasPermission("psm.indent.view", "psm.indent.view_self")]

    def get(self, request, pk):
        indent = get_object_or_404(queries.indents_for(actor(request)), pk=pk)
        versions = IndentVersion.objects.filter(indent=indent).order_by("version")
        decisions = ApprovalDecision.objects.filter(indent=indent).order_by("created_at")
        audit = AuditEvent.objects.filter(object_type="Indent", object_id=indent.pk).order_by(
            "created_at"
        )
        return Response(
            {
                "versions": [
                    {
                        "version": x.version,
                        "snapshot": x.snapshot,
                        "changed_by_id": x.changed_by_id,
                        "created_at": x.created_at,
                    }
                    for x in versions
                ],
                "decisions": [
                    {
                        "role": x.role,
                        "decision": x.decision,
                        "justification": x.justification,
                        "created_at": x.created_at,
                    }
                    for x in decisions
                ],
                "audit": [
                    {
                        "action": x.action,
                        "actor_id": x.actor_id,
                        "details": x.details,
                        "created_at": x.created_at,
                    }
                    for x in audit
                ],
            }
        )


class InventoryView(APIView):
    serializer_class = s.InventorySerializer
    permission_classes = [MODULE, HasPermission("psm.stock.view", "psm.stock.manage")]

    def get(self, request):
        rows = queries.inventory_for(actor(request)).order_by("item_code", "location_id")
        if request.query_params.get("item_code"):
            rows = rows.filter(item_code=request.query_params["item_code"])
        return Response(s.InventorySerializer(rows[:500], many=True).data)

    def post(self, request):
        if not actor(request).has_permission("psm.stock.manage"):
            raise PermissionDenied
        payload = s.InventorySerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        scope = queries.department_scope(actor(request))
        department_id = payload.validated_data.get("department_id")
        if scope is not None and (department_id is None or department_id not in scope):
            raise PermissionDenied("You may manage stock only for your assigned department.")
        balance, _ = InventoryBalance.objects.update_or_create(
            item_code=payload.validated_data["item_code"],
            location_id=payload.validated_data["location_id"],
            department_id=payload.validated_data.get("department_id"),
            defaults=payload.validated_data,
        )
        AuditEvent.objects.create(
            actor_id=actor(request).user_id,
            action="stock.balance_updated",
            object_type="InventoryBalance",
            object_id=balance.pk,
            details={"quantity_on_hand": str(balance.quantity_on_hand)},
        )
        return Response(s.InventorySerializer(balance).data, status=201)


class VendorCollectionView(APIView):
    serializer_class = s.VendorSerializer
    permission_classes = [MODULE]

    def get_permissions(self):
        return [MODULE, HasPermission("psm.vendor.view", "psm.vendor.manage")]

    def get(self, request):
        return Response(
            s.VendorSerializer(queries.vendors_for(actor(request))[:250], many=True).data
        )

    def post(self, request):
        if not actor(request).has_permission("psm.vendor.manage"):
            raise PermissionDenied
        payload = s.VendorSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        vendor = run_rule(svc.save_vendor, actor=actor(request), data=payload.validated_data)
        return Response(s.VendorSerializer(vendor).data, status=201)


class VendorVerifyView(APIView):
    serializer_class = s.VendorSerializer
    permission_classes = [MODULE, HasPermission("psm.vendor.manage")]

    def post(self, request, pk):
        vendor = get_object_or_404(Vendor, pk=pk)
        vendor = run_rule(svc.verify_vendor, vendor=vendor, actor=actor(request))
        return Response(s.VendorSerializer(vendor).data)


class PurchaseOrderCollectionView(APIView):
    serializer_class = s.PurchaseOrderSerializer
    permission_classes = [MODULE]

    def get_permissions(self):
        return [
            MODULE,
            HasPermission("psm.procurement.manage", "psm.invoice.manage", "psm.indent.view_self"),
        ]

    def get(self, request):
        return Response(
            s.PurchaseOrderSerializer(
                queries.purchase_orders_for(actor(request))[:250], many=True
            ).data
        )

    def post(self, request):
        if not actor(request).has_permission("psm.procurement.manage"):
            raise PermissionDenied
        indent = get_object_or_404(queries.indents_for(actor(request)), pk=request.data.get("indent"))
        vendor = get_object_or_404(Vendor, pk=request.data.get("vendor"))
        po = run_rule(
            svc.issue_purchase_order,
            indent=indent,
            vendor=vendor,
            actor=actor(request),
            total_amount=request.data.get("total_amount"),
            planned_delivery_at=request.data.get("planned_delivery_at"),
        )
        return Response(s.PurchaseOrderSerializer(po).data, status=201)


class GoodsReceiptView(APIView):
    serializer_class = s.GoodsReceiptSerializer
    permission_classes = [MODULE]

    def get_permissions(self):
        code = "psm.receipt.manage" if self.request.method == "POST" else "psm.indent.view"
        return [MODULE, HasPermission(code)]

    def get(self, request):
        rows = queries.receipts_for(actor(request))
        return Response(
            s.GoodsReceiptSerializer(rows.order_by("-created_at")[:250], many=True).data
        )

    def post(self, request):
        po = get_object_or_404(
            queries.purchase_orders_for(actor(request)), pk=request.data.get("purchase_order")
        )
        receipt = run_rule(
            svc.record_receipt,
            purchase_order=po,
            actor=actor(request),
            lines=request.data.get("lines", []),
            evidence=request.data.get("evidence"),
        )
        return Response(s.GoodsReceiptSerializer(receipt).data, status=201)


class GoodsReceiptConfirmView(APIView):
    serializer_class = s.GoodsReceiptSerializer
    permission_classes = [MODULE, HasPermission("psm.indent.create")]

    def post(self, request, pk):
        receipt = get_object_or_404(queries.receipts_for(actor(request)), pk=pk)
        receipt = run_rule(
            svc.confirm_receipt,
            receipt=receipt,
            actor=actor(request),
            destination_location_id=request.data.get("location_id"),
        )
        return Response(s.GoodsReceiptSerializer(receipt).data)


class InvoiceCollectionView(APIView):
    serializer_class = s.InvoiceCreateSerializer
    permission_classes = [MODULE]

    def get_permissions(self):
        return [MODULE, HasPermission("psm.invoice.manage", "psm.indent.view_self")]

    def get(self, request):
        rows = Invoice.objects.select_related("purchase_order", "purchase_order__indent")
        scope = queries.department_scope(actor(request))
        if scope is not None:
            rows = rows.filter(purchase_order__indent__department_id__in=scope)
        elif not actor(request).has_permission("psm.invoice.manage"):
            rows = rows.filter(purchase_order__indent__requestor_id=actor(request).user_id)
        return Response(
            [
                {
                    "id": x.pk,
                    "purchase_order": x.purchase_order_id,
                    "vendor_invoice_number": x.vendor_invoice_number,
                    "invoice_amount": x.invoice_amount,
                    "matched_amount": x.matched_amount,
                    "status": x.status,
                }
                for x in rows[:250]
            ]
        )

    def post(self, request):
        if not actor(request).has_permission("psm.invoice.manage"):
            raise PermissionDenied
        payload = s.InvoiceCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        invoice = payload.save()
        return Response({"id": invoice.pk, "status": invoice.status}, status=201)


class InvoiceVerifyView(APIView):
    serializer_class = s.InvoiceCreateSerializer
    permission_classes = [MODULE, HasPermission("psm.invoice.manage")]

    def post(self, request, pk):
        invoice = get_object_or_404(
            Invoice.objects.filter(
                purchase_order__in=queries.purchase_orders_for(actor(request))
            ),
            pk=pk,
        )
        invoice = run_rule(svc.verify_invoice, invoice=invoice, actor=actor(request))
        return Response(
            {"id": invoice.pk, "status": invoice.status, "matched_amount": invoice.matched_amount}
        )


class PaymentView(APIView):
    serializer_class = s.PaymentResultSerializer
    permission_classes = [MODULE, HasPermission("psm.invoice.manage")]

    def post(self, request, pk):
        invoice = get_object_or_404(
            Invoice.objects.filter(
                purchase_order__in=queries.purchase_orders_for(actor(request))
            ),
            pk=pk,
        )
        payment = run_rule(
            svc.process_payment,
            invoice=invoice,
            actor=actor(request),
            amount=request.data.get("amount", 0),
            reference=request.data.get("reference", ""),
        )
        return Response(
            {"id": payment.pk, "amount": payment.amount, "processed_at": payment.processed_at},
            status=201,
        )


class PolicyView(APIView):
    serializer_class = s.PolicyReadSerializer
    permission_classes = [MODULE, HasPermission("psm.procurement.manage")]

    def get(self, request):
        return Response(
            list(Policy.objects.filter(active=True).values("key", "value", "description"))
        )

    def put(self, request):
        key = str(request.data.get("key", "")).strip()
        if not key or "value" not in request.data:
            raise ValidationError("key and value are required.")
        row, _ = Policy.objects.update_or_create(
            key=key,
            defaults={
                "value": request.data["value"],
                "description": request.data.get("description", ""),
                "active": True,
            },
        )
        AuditEvent.objects.create(
            actor_id=actor(request).user_id,
            action="policy.updated",
            object_type="Policy",
            object_id=row.pk,
            details={"key": row.key},
        )
        return Response({"key": row.key, "value": row.value})


class DashboardView(APIView):
    serializer_class = s.DashboardSerializer
    permission_classes = [MODULE, HasPermission("psm.report.view")]

    def get(self, request):
        data = {
            "indents_by_status": list(Indent.objects.values("status").annotate(count=Count("id"))),
            "stock_items": InventoryBalance.objects.count(),
            "stock_units": InventoryBalance.objects.aggregate(total=Sum("quantity_on_hand"))[
                "total"
            ]
            or 0,
            "open_purchase_orders": PurchaseOrder.objects.exclude(
                status__in=("received", "cancelled")
            ).count(),
            "held_invoices": Invoice.objects.filter(status="held").count(),
        }
        ReportRun.objects.create(
            report="dashboard",
            requested_by_id=actor(request).user_id,
            filters=dict(request.query_params),
            output_format="json",
        )
        return Response(data)


class ReportExportView(APIView):
    serializer_class = s.IndentReadSerializer
    permission_classes = [MODULE, HasPermission("psm.report.view")]

    def get(self, request):
        filters = {
            key: request.query_params[key]
            for key in ("status", "department_id")
            if request.query_params.get(key)
        }
        rows = Indent.objects.all()
        if filters.get("status"):
            rows = rows.filter(status=filters["status"])
        if filters.get("department_id"):
            rows = rows.filter(department_id=filters["department_id"])
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="psm-indents.csv"'
        writer = csv.writer(response)
        writer.writerow(
            (
                "indent_number",
                "requestor_id",
                "department_id",
                "status",
                "estimated_total",
                "created_at",
            )
        )
        for row in rows.order_by("-created_at")[:10000]:
            writer.writerow(
                (
                    row.indent_number,
                    row.requestor_id,
                    row.department_id,
                    row.status,
                    row.estimated_total,
                    row.created_at.isoformat(),
                )
            )
        run = ReportRun.objects.create(
            report="operations",
            requested_by_id=actor(request).user_id,
            filters=filters,
            output_format="csv",
            result={"row_count": min(rows.count(), 10000)},
        )
        AuditEvent.objects.create(
            actor_id=actor(request).user_id,
            action="report.generated",
            object_type="ReportRun",
            object_id=run.pk,
            details={"format": "csv"},
        )
        return response


class ReportScheduleView(APIView):
    serializer_class = s.ReportScheduleSerializer
    permission_classes = [MODULE, HasPermission("psm.report.view")]

    def get(self, request):
        rows = ReportSchedule.objects.filter(created_by_id=actor(request).user_id).order_by(
            "next_run_at"
        )
        return Response(
            [
                {
                    "id": x.pk,
                    "report": x.report,
                    "filters": x.filters,
                    "interval_seconds": x.interval_seconds,
                    "next_run_at": x.next_run_at,
                    "last_run_at": x.last_run_at,
                    "active": x.active,
                }
                for x in rows
            ]
        )

    def post(self, request):
        payload = s.ReportScheduleSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        try:
            svc.report_snapshot(data["report"], data["filters"])
        except svc.PSMRuleError as exc:
            raise ValidationError({"report": str(exc)}) from exc
        schedule = ReportSchedule.objects.create(created_by_id=actor(request).user_id, **data)
        AuditEvent.objects.create(
            actor_id=actor(request).user_id,
            action="report.scheduled",
            object_type="ReportSchedule",
            object_id=schedule.pk,
            details={"report": schedule.report, "interval_seconds": schedule.interval_seconds},
        )
        return Response(s.ReportScheduleSerializer(schedule).data, status=201)


class ReportScheduleDetailView(APIView):
    serializer_class = s.ReportScheduleSerializer
    permission_classes = [MODULE, HasPermission("psm.report.view")]

    def delete(self, request, pk):
        schedule = get_object_or_404(ReportSchedule, pk=pk, created_by_id=actor(request).user_id)
        schedule.active = False
        schedule.save(update_fields=("active", "updated_at"))
        AuditEvent.objects.create(
            actor_id=actor(request).user_id,
            action="report.schedule_cancelled",
            object_type="ReportSchedule",
            object_id=schedule.pk,
            details={},
        )
        return Response(status=204)


class AuditView(APIView):
    serializer_class = s.AuditEventSerializer
    permission_classes = [MODULE, HasPermission("psm.audit.view")]

    def get(self, request):
        rows = queries.audit_for(actor(request)).order_by("-created_at")[:250]
        return Response(
            [
                {
                    "id": x.pk,
                    "actor_id": x.actor_id,
                    "action": x.action,
                    "object_type": x.object_type,
                    "object_id": x.object_id,
                    "details": x.details,
                    "created_at": x.created_at,
                }
                for x in rows
            ]
        )


class CommunicationHistoryView(APIView):
    serializer_class = s.CommunicationSerializer
    permission_classes = [MODULE]

    def get_permissions(self):
        return [MODULE, HasPermission("psm.indent.view", "psm.indent.view_self")]

    def get(self, request):
        rows = Communication.objects.all()
        if not actor(request).has_permission("psm.indent.view"):
            rows = rows.filter(recipient_id=actor(request).user_id)
        rows = rows.order_by("-created_at")[:250]
        return Response(
            [
                {
                    "id": item.pk,
                    "event": item.event,
                    "subject": item.subject,
                    "body": item.body,
                    "delivery_status": item.delivery_status,
                    "created_at": item.created_at,
                    "delivered_at": item.delivered_at,
                }
                for item in rows
            ]
        )


class TenderCollectionView(APIView):
    serializer_class = s.TenderSerializer
    permission_classes = [MODULE, HasPermission("psm.procurement.manage")]

    def get(self, request):
        rows = Tender.objects.select_related("indent", "selected_bid").order_by("-created_at")[:200]
        return Response(
            [
                {
                    "id": x.pk,
                    "indent": x.indent_id,
                    "tender_number": x.tender_number,
                    "status": x.status,
                    "published_at": x.published_at,
                    "closes_at": x.closes_at,
                    "criteria": x.evaluation_criteria,
                    "selected_bid": x.selected_bid_id,
                }
                for x in rows
            ]
        )

    def post(self, request):
        indent = get_object_or_404(queries.indents_for(actor(request)), pk=request.data.get("indent"))
        tender = run_rule(
            svc.create_tender,
            indent=indent,
            actor=actor(request),
            closes_at=request.data.get("closes_at"),
            criteria=request.data.get("criteria", []),
        )
        return Response(
            {"id": tender.pk, "tender_number": tender.tender_number, "status": tender.status},
            status=201,
        )


class TenderActionView(APIView):
    serializer_class = s.TenderSerializer
    permission_classes = [MODULE]

    @extend_schema(operation_id="psm_tender_action")
    def post(self, request, pk, action):
        tender = get_object_or_404(Tender, pk=pk)
        if action == "publish":
            if not actor(request).has_permission("psm.procurement.manage"):
                raise PermissionDenied
            tender = run_rule(svc.publish_tender, tender=tender, actor=actor(request))
        elif action == "bids":
            if not actor(request).has_permission("psm.procurement.manage"):
                raise PermissionDenied
            vendor = get_object_or_404(Vendor, pk=request.data.get("vendor"))
            bid = run_rule(
                svc.submit_bid,
                tender=tender,
                vendor=vendor,
                actor=actor(request),
                amount=request.data.get("amount", 0),
                submission=request.data.get("submission", {}),
            )
            return Response({"id": bid.pk, "status": bid.status}, status=201)
        elif action == "award":
            if not actor(request).has_permission("psm.tender.evaluate"):
                raise PermissionDenied
            bid = get_object_or_404(Bid, pk=request.data.get("bid"))
            tender = run_rule(
                svc.award_tender,
                tender=tender,
                bid=bid,
                actor=actor(request),
                evaluation=request.data.get("evaluation", {}),
            )
        else:
            return Response({"detail": "Unknown tender action."}, status=404)
        return Response(
            {"id": tender.pk, "status": tender.status, "selected_bid": tender.selected_bid_id}
        )


class DiscrepancyCollectionView(APIView):
    serializer_class = s.DiscrepancySerializer
    permission_classes = [MODULE, HasPermission("psm.receipt.manage", "psm.procurement.manage")]

    def get(self, request):
        rows = queries.discrepancies_for(actor(request)).order_by("-created_at")[:200]
        return Response(
            [
                {
                    "id": x.pk,
                    "receipt": x.receipt_id,
                    "description": x.description,
                    "evidence": x.evidence,
                    "status": x.status,
                    "resolution": x.resolution,
                    "resolution_notes": x.resolution_notes,
                }
                for x in rows
            ]
        )

    def post(self, request):
        if not actor(request).has_permission("psm.receipt.manage"):
            raise PermissionDenied
        receipt = get_object_or_404(
            queries.receipts_for(actor(request)), pk=request.data.get("receipt")
        )
        case = run_rule(
            svc.open_discrepancy,
            receipt=receipt,
            actor=actor(request),
            description=str(request.data.get("description", "")),
            evidence=request.data.get("evidence", []),
        )
        return Response({"id": case.pk, "status": case.status}, status=201)


class DiscrepancyResolveView(APIView):
    serializer_class = s.DiscrepancySerializer
    permission_classes = [MODULE, HasPermission("psm.procurement.manage")]

    def post(self, request, pk):
        case = get_object_or_404(queries.discrepancies_for(actor(request)), pk=pk)
        case = run_rule(
            svc.resolve_discrepancy,
            case=case,
            actor=actor(request),
            resolution=str(request.data.get("resolution", "")),
            notes=str(request.data.get("notes", "")),
        )
        return Response({"id": case.pk, "status": case.status, "resolution": case.resolution})


class StockTransferCollectionView(APIView):
    serializer_class = s.TransferReadSerializer
    permission_classes = [MODULE]

    def get_permissions(self):
        if self.request.method == "GET":
            return [MODULE, HasPermission("psm.stock.view", "psm.stock.manage")]
        return [MODULE, HasPermission("psm.stock.manage")]

    def get(self, request):
        rows = queries.transfers_for(actor(request)).prefetch_related("lines").order_by(
            "-created_at"
        )[:200]
        return Response(
            [
                {
                    "id": x.pk,
                    "source_department_id": x.source_department_id,
                    "destination_department_id": x.destination_department_id,
                    "status": x.status,
                    "lines": list(x.lines.values("item_code", "quantity")),
                }
                for x in rows
            ]
        )

    def post(self, request):
        scope = queries.department_scope(actor(request))
        requested_department = int(request.data.get("source_department_id", 0))
        if scope is not None and requested_department not in scope:
            raise PermissionDenied("You may transfer stock only from your assigned department.")
        transfer = run_rule(
            svc.request_stock_transfer,
            actor=actor(request),
            source_department_id=int(request.data.get("source_department_id", 0)),
            destination_department_id=int(request.data.get("destination_department_id", 0)),
            lines=request.data.get("lines", []),
        )
        return Response({"id": transfer.pk, "status": transfer.status}, status=201)


class StockTransferActionView(APIView):
    serializer_class = s.TransferReadSerializer
    permission_classes = [MODULE, HasPermission("psm.stock.manage")]

    @extend_schema(operation_id="psm_stock_transfer_action")
    def post(self, request, pk, action):
        transfer = get_object_or_404(queries.transfers_for(actor(request)), pk=pk)
        scope = queries.department_scope(actor(request))
        if action == "dispatch":
            if scope is not None and transfer.source_department_id not in scope:
                raise PermissionDenied("Only the source department may dispatch this transfer.")
            transfer = run_rule(
                svc.dispatch_stock_transfer, transfer=transfer, actor=actor(request)
            )
        elif action == "receive":
            if scope is not None and transfer.destination_department_id not in scope:
                raise PermissionDenied("Only the destination department may receive this transfer.")
            transfer = run_rule(
                svc.confirm_stock_transfer,
                transfer=transfer,
                actor=actor(request),
                destination_location_id=int(request.data.get("location_id", 0)),
            )
        else:
            return Response({"detail": "Unknown stock-transfer action."}, status=404)
        return Response({"id": transfer.pk, "status": transfer.status})


class VendorUpdateView(APIView):
    serializer_class = s.VendorSerializer
    permission_classes = [MODULE, HasPermission("psm.vendor.manage")]

    def put(self, request, pk):
        vendor = get_object_or_404(Vendor, pk=pk)
        payload = s.VendorSerializer(vendor, data=request.data)
        payload.is_valid(raise_exception=True)
        vendor = run_rule(
            svc.save_vendor, actor=actor(request), data=payload.validated_data, vendor=vendor
        )
        return Response(s.VendorSerializer(vendor).data)
