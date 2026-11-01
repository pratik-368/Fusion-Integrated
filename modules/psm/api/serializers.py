from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from modules.psm.models import (
    GoodsReceipt,
    Indent,
    IndentLine,
    InventoryBalance,
    Invoice,
    PurchaseOrder,
    StockTransfer,
    Vendor,
)


class IndentLineWriteSerializer(serializers.Serializer):
    item_code = serializers.CharField(max_length=80, allow_blank=True, required=False, default="")
    description = serializers.CharField(max_length=300)
    quantity = serializers.DecimalField(max_digits=12, decimal_places=3)
    estimated_unit_cost = serializers.DecimalField(max_digits=14, decimal_places=2)
    unit = serializers.CharField(max_length=30, allow_blank=True, required=False, default="")


class IndentCreateSerializer(serializers.Serializer):
    justification = serializers.CharField(max_length=4000)
    priority = serializers.CharField(max_length=20, allow_blank=True, required=False, default="")
    criticality = serializers.CharField(max_length=80, allow_blank=True, required=False, default="")
    lines = IndentLineWriteSerializer(many=True, allow_empty=False)


class IndentLineReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = IndentLine
        fields = ("id", "item_code", "description", "quantity", "estimated_unit_cost", "unit")


class IndentReadSerializer(serializers.ModelSerializer):
    lines = serializers.SerializerMethodField()

    @extend_schema_field(IndentLineReadSerializer(many=True))
    def get_lines(self, obj):
        return IndentLineReadSerializer(obj.lines.filter(active=True), many=True).data

    class Meta:
        model = Indent
        fields = (
            "id",
            "indent_number",
            "requestor_id",
            "department_id",
            "status",
            "justification",
            "priority",
            "criticality",
            "estimated_total",
            "lines",
            "created_at",
            "submitted_at",
            "closed_at",
        )


class InventorySerializer(serializers.ModelSerializer):
    class Meta:
        model = InventoryBalance
        fields = (
            "id",
            "item_code",
            "description",
            "location_id",
            "department_id",
            "quantity_on_hand",
            "updated_at",
        )
        read_only_fields = ("id", "updated_at")


class VendorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Vendor
        fields = (
            "id",
            "name",
            "contact_email",
            "gst_number",
            "bank_details",
            "compliance_documents",
            "verified",
            "active",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "verified", "created_at", "updated_at")


class PurchaseOrderSerializer(serializers.ModelSerializer):
    class Meta:
        model = PurchaseOrder
        fields = (
            "id",
            "indent",
            "vendor",
            "po_number",
            "status",
            "total_amount",
            "planned_delivery_at",
            "actual_delivery_at",
            "issued_at",
        )
        read_only_fields = ("id", "po_number", "status", "actual_delivery_at", "issued_at")


class GoodsReceiptSerializer(serializers.ModelSerializer):
    class Meta:
        model = GoodsReceipt
        fields = (
            "id",
            "purchase_order",
            "grn_number",
            "inspected_by_id",
            "status",
            "discrepancy_open",
            "evidence",
            "confirmed_at",
            "created_at",
        )
        read_only_fields = fields


class InvoiceCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Invoice
        fields = ("purchase_order", "vendor_invoice_number", "invoice_amount")


class StockTransferSerializer(serializers.ModelSerializer):
    class Meta:
        model = StockTransfer
        fields = (
            "id",
            "requested_by_id",
            "source_department_id",
            "destination_department_id",
            "status",
            "dispatched_at",
            "received_at",
            "created_at",
        )
        read_only_fields = fields


class ActionResultSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    status = serializers.CharField()


class StockCheckResultSerializer(serializers.Serializer):
    reserved = serializers.BooleanField()
    available = serializers.BooleanField()
    indent = IndentReadSerializer()


class PaymentResultSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    amount = serializers.DecimalField(max_digits=14, decimal_places=2)
    processed_at = serializers.DateTimeField()


class DashboardSerializer(serializers.Serializer):
    indents_by_status = serializers.ListField(child=serializers.DictField())
    stock_items = serializers.IntegerField()
    stock_units = serializers.DecimalField(max_digits=18, decimal_places=3)
    open_purchase_orders = serializers.IntegerField()
    held_invoices = serializers.IntegerField()


class AuditEventSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    actor_id = serializers.IntegerField(allow_null=True)
    action = serializers.CharField()
    object_type = serializers.CharField()
    object_id = serializers.IntegerField()
    details = serializers.JSONField()
    created_at = serializers.DateTimeField()


class TenderSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    indent = serializers.IntegerField()
    tender_number = serializers.CharField()
    status = serializers.CharField()
    published_at = serializers.DateTimeField(allow_null=True)
    closes_at = serializers.DateTimeField(allow_null=True)
    criteria = serializers.JSONField()
    selected_bid = serializers.IntegerField(allow_null=True)


class DiscrepancySerializer(serializers.Serializer):
    id = serializers.IntegerField()
    receipt = serializers.IntegerField()
    description = serializers.CharField()
    evidence = serializers.JSONField()
    status = serializers.CharField()
    resolution = serializers.CharField()
    resolution_notes = serializers.CharField()


class TransferReadSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    source_department_id = serializers.IntegerField()
    destination_department_id = serializers.IntegerField()
    status = serializers.CharField()
    lines = serializers.ListField(child=serializers.DictField())


class PolicyReadSerializer(serializers.Serializer):
    key = serializers.CharField()
    value = serializers.JSONField()
    description = serializers.CharField()


class IndentHistorySerializer(serializers.Serializer):
    versions = serializers.ListField(child=serializers.DictField())
    decisions = serializers.ListField(child=serializers.DictField())
    audit = serializers.ListField(child=serializers.DictField())


class ReportScheduleSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    report = serializers.ChoiceField(choices=("operations", "stock", "procurement", "financial"))
    filters = serializers.JSONField(required=False, default=dict)
    interval_seconds = serializers.IntegerField(min_value=1)
    next_run_at = serializers.DateTimeField()
    active = serializers.BooleanField(read_only=True)


class ReportRunSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    report = serializers.CharField()
    requested_by_id = serializers.IntegerField()
    filters = serializers.JSONField()
    output_format = serializers.CharField()
    result = serializers.JSONField()
    generated_at = serializers.DateTimeField()


class CommunicationSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    event = serializers.CharField()
    subject = serializers.CharField()
    body = serializers.CharField()
    delivery_status = serializers.CharField()
    created_at = serializers.DateTimeField()
    delivered_at = serializers.DateTimeField(allow_null=True)


