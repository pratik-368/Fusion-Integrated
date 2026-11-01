"""Persistence owned by the Purchase and Stores bounded context."""

from django.db import models


class PSMModel(models.Model):
    class Meta:
        abstract = True

    def __str__(self):
        return str(self.pk)


class Timestamped(PSMModel):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Policy(Timestamped):
    """Institution-configured values; policy parameters are intentionally not guessed."""

    key = models.SlugField(max_length=80, unique=True)
    value = models.JSONField(default=dict)
    description = models.CharField(max_length=300, blank=True)
    active = models.BooleanField(default=True)


class DepartmentAssignment(PSMModel):
    ROLE_CHOICES = (
        ("employee", "Employee"),
        ("department_admin", "Department Admin"),
        ("department_head", "Department Head"),
    )
    user_id = models.PositiveBigIntegerField(db_index=True)
    department_id = models.PositiveBigIntegerField(db_index=True)
    role = models.CharField(max_length=32, choices=ROLE_CHOICES)
    assigned_by_id = models.PositiveBigIntegerField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints = [models.UniqueConstraint(
            fields=("user_id", "department_id", "role"), name="psm_department_assignment_unique")]


class Indent(Timestamped):
    STATUS = [
        (v, v.replace("_", " ").title())
        for v in (
            "draft",
            "submitted",
            "stock_reserved",
            "internal_issue",
            "department_review",
            "head_review",
            "procurement_review",
            "final_approval",
            "procurement_authorized",
            "tender",
            "po_issued",
            "partially_received",
            "received",
            "rejected",
            "withdrawn",
            "cancelled",
        )
    ]
    indent_number = models.CharField(max_length=32, unique=True, db_index=True)
    requestor_id = models.PositiveBigIntegerField(db_index=True)
    department_id = models.PositiveBigIntegerField(db_index=True)
    status = models.CharField(max_length=32, choices=STATUS, default="draft", db_index=True)
    justification = models.TextField(max_length=4000)
    priority = models.CharField(max_length=20, blank=True)
    criticality = models.CharField(max_length=80, blank=True)
    estimated_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    source_indent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="reorders"
    )
    current_approver_role = models.CharField(max_length=80, blank=True)
    selected_procurement_method = models.CharField(max_length=20, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("status", "-created_at"), name="psm_indent_status_recent"),
            models.Index(fields=("requestor_id", "-created_at"), name="psm_indent_owner_recent"),
        ]


class IndentLine(Timestamped):
    indent = models.ForeignKey(Indent, on_delete=models.CASCADE, related_name="lines")
    item_code = models.CharField(max_length=80, blank=True)
    description = models.CharField(max_length=300)
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    estimated_unit_cost = models.DecimalField(max_digits=14, decimal_places=2)
    unit = models.CharField(max_length=30, blank=True)
    active = models.BooleanField(default=True, db_index=True)


class IndentVersion(PSMModel):
    indent = models.ForeignKey(Indent, on_delete=models.CASCADE, related_name="versions")
    version = models.PositiveIntegerField()
    snapshot = models.JSONField()
    changed_by_id = models.PositiveBigIntegerField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("indent", "version"), name="psm_indent_version_unique")
        ]


class InventoryBalance(Timestamped):
    item_code = models.CharField(max_length=80, db_index=True)
    description = models.CharField(max_length=300, blank=True)
    location_id = models.PositiveBigIntegerField(db_index=True)
    department_id = models.PositiveBigIntegerField(null=True, blank=True, db_index=True)
    quantity_on_hand = models.DecimalField(max_digits=14, decimal_places=3, default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("item_code", "location_id", "department_id"),
                name="psm_inventory_location_item_unique",
            )
        ]


class StockReservation(Timestamped):
    indent = models.ForeignKey(Indent, on_delete=models.PROTECT, related_name="reservations")
    line = models.ForeignKey(IndentLine, on_delete=models.PROTECT, related_name="reservations")
    balance = models.ForeignKey(
        InventoryBalance, on_delete=models.PROTECT, related_name="reservations"
    )
    quantity = models.DecimalField(max_digits=14, decimal_places=3)
    released_at = models.DateTimeField(null=True, blank=True)


class InternalIssue(Timestamped):
    indent = models.OneToOneField(Indent, on_delete=models.PROTECT, related_name="internal_issue")
    status = models.CharField(max_length=30, default="scheduled")
    scheduled_for = models.DateTimeField(null=True, blank=True)
    dispatched_by_id = models.PositiveBigIntegerField(null=True)
    dispatched_at = models.DateTimeField(null=True)
    acknowledged_by_id = models.PositiveBigIntegerField(null=True)
    acknowledged_at = models.DateTimeField(null=True)
    discrepancy_notes = models.TextField(blank=True)


class ApprovalDecision(PSMModel):
    indent = models.ForeignKey(Indent, on_delete=models.CASCADE, related_name="decisions")
    actor_id = models.PositiveBigIntegerField()
    role = models.CharField(max_length=80)
    decision = models.CharField(max_length=20)
    justification = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class Vendor(Timestamped):
    name = models.CharField(max_length=200)
    contact_email = models.EmailField(blank=True)
    gst_number = models.CharField(max_length=20, blank=True)
    bank_details = models.JSONField(default=dict)
    compliance_documents = models.JSONField(default=list)
    verified = models.BooleanField(default=False, db_index=True)
    active = models.BooleanField(default=True)
    created_by_id = models.PositiveBigIntegerField(null=True)


class VendorVersion(PSMModel):
    vendor = models.ForeignKey(Vendor, on_delete=models.CASCADE, related_name="versions")
    version = models.PositiveIntegerField()
    snapshot = models.JSONField()
    changed_by_id = models.PositiveBigIntegerField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("vendor", "version"), name="psm_vendor_version_unique")
        ]


class Tender(Timestamped):
    indent = models.OneToOneField(Indent, on_delete=models.PROTECT, related_name="tender")
    tender_number = models.CharField(max_length=40, unique=True)
    status = models.CharField(max_length=30, default="draft", db_index=True)
    published_at = models.DateTimeField(null=True, blank=True)
    closes_at = models.DateTimeField(null=True, blank=True)
    evaluation_criteria = models.JSONField(default=list)
    selected_bid = models.ForeignKey(
        "Bid", null=True, blank=True, on_delete=models.SET_NULL, related_name="selected_for_tenders"
    )
    approved_by_id = models.PositiveBigIntegerField(null=True)


class Bid(Timestamped):
    tender = models.ForeignKey(Tender, on_delete=models.CASCADE, related_name="bids")
    vendor = models.ForeignKey(Vendor, on_delete=models.PROTECT, related_name="bids")
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    submission = models.JSONField(default=dict)
    evaluation = models.JSONField(default=dict)
    status = models.CharField(max_length=30, default="submitted")


class PurchaseOrder(Timestamped):
    indent = models.ForeignKey(Indent, on_delete=models.PROTECT, related_name="purchase_orders")
    vendor = models.ForeignKey(Vendor, on_delete=models.PROTECT, related_name="purchase_orders")
    po_number = models.CharField(max_length=40, unique=True)
    status = models.CharField(max_length=30, default="issued", db_index=True)
    total_amount = models.DecimalField(max_digits=14, decimal_places=2)
    planned_delivery_at = models.DateTimeField(null=True, blank=True)
    actual_delivery_at = models.DateTimeField(null=True, blank=True)
    issued_by_id = models.PositiveBigIntegerField()
    issued_at = models.DateTimeField(auto_now_add=True)


class GoodsReceipt(Timestamped):
    purchase_order = models.ForeignKey(
        PurchaseOrder, on_delete=models.PROTECT, related_name="receipts"
    )
    grn_number = models.CharField(max_length=40, unique=True)
    inspected_by_id = models.PositiveBigIntegerField()
    status = models.CharField(max_length=30, default="inspection", db_index=True)
    discrepancy_open = models.BooleanField(default=False)
    evidence = models.JSONField(default=list)
    confirmed_by_id = models.PositiveBigIntegerField(null=True)
    confirmed_at = models.DateTimeField(null=True)


class GoodsReceiptLine(PSMModel):
    receipt = models.ForeignKey(GoodsReceipt, on_delete=models.CASCADE, related_name="lines")
    indent_line = models.ForeignKey(IndentLine, on_delete=models.PROTECT)
    accepted_quantity = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    rejected_quantity = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    notes = models.CharField(max_length=500, blank=True)


class DiscrepancyCase(Timestamped):
    receipt = models.ForeignKey(GoodsReceipt, on_delete=models.PROTECT, related_name="cases")
    opened_by_id = models.PositiveBigIntegerField()
    description = models.TextField(max_length=3000)
    evidence = models.JSONField(default=list)
    status = models.CharField(max_length=30, default="open", db_index=True)
    resolution = models.CharField(max_length=30, blank=True)
    resolution_notes = models.TextField(blank=True)


class Invoice(Timestamped):
    purchase_order = models.ForeignKey(
        PurchaseOrder, on_delete=models.PROTECT, related_name="invoices"
    )
    vendor_invoice_number = models.CharField(max_length=80)
    invoice_amount = models.DecimalField(max_digits=14, decimal_places=2)
    matched_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    status = models.CharField(max_length=20, default="pending", db_index=True)
    verified_by_id = models.PositiveBigIntegerField(null=True)
    verified_at = models.DateTimeField(null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("purchase_order", "vendor_invoice_number"),
                name="psm_invoice_vendor_ref_unique",
            )
        ]


class Payment(Timestamped):
    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="payments")
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    reference = models.CharField(max_length=100, blank=True)
    processed_by_id = models.PositiveBigIntegerField()
    processed_at = models.DateTimeField(auto_now_add=True)


class StockTransfer(Timestamped):
    requested_by_id = models.PositiveBigIntegerField()
    source_department_id = models.PositiveBigIntegerField()
    destination_department_id = models.PositiveBigIntegerField()
    status = models.CharField(max_length=24, default="requested", db_index=True)
    dispatched_at = models.DateTimeField(null=True)
    received_at = models.DateTimeField(null=True)


class StockTransferLine(PSMModel):
    transfer = models.ForeignKey(StockTransfer, on_delete=models.CASCADE, related_name="lines")
    item_code = models.CharField(max_length=80)
    quantity = models.DecimalField(max_digits=14, decimal_places=3)
    source_balance = models.ForeignKey(
        InventoryBalance, null=True, blank=True, on_delete=models.PROTECT
    )


class StockMovement(PSMModel):
    item_code = models.CharField(max_length=80, db_index=True)
    location_id = models.PositiveBigIntegerField(db_index=True)
    quantity_delta = models.DecimalField(max_digits=14, decimal_places=3)
    reference_type = models.CharField(max_length=30)
    reference_id = models.PositiveBigIntegerField()
    actor_id = models.PositiveBigIntegerField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=("item_code", "-created_at"), name="psm_movement_item_recent")
        ]


class AuditEvent(PSMModel):
    actor_id = models.PositiveBigIntegerField(null=True, db_index=True)
    action = models.CharField(max_length=100, db_index=True)
    object_type = models.CharField(max_length=80)
    object_id = models.PositiveBigIntegerField()
    details = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)


class Communication(PSMModel):
    recipient_id = models.PositiveBigIntegerField(null=True, blank=True, db_index=True)
    recipient_email = models.EmailField(blank=True)
    event = models.CharField(max_length=80)
    subject = models.CharField(max_length=200)
    body = models.TextField()
    reference_type = models.CharField(max_length=40)
    reference_id = models.PositiveBigIntegerField()
    delivery_status = models.CharField(max_length=16, default="pending", db_index=True)
    delivery_attempts = models.PositiveSmallIntegerField(default=0)
    last_error = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)


class ReportRun(PSMModel):
    report = models.CharField(max_length=80)
    requested_by_id = models.PositiveBigIntegerField(db_index=True)
    filters = models.JSONField(default=dict)
    output_format = models.CharField(max_length=10, default="json")
    result = models.JSONField(default=dict)
    generated_at = models.DateTimeField(auto_now_add=True)


class ReportSchedule(Timestamped):
    report = models.CharField(max_length=80)
    created_by_id = models.PositiveBigIntegerField(db_index=True)
    filters = models.JSONField(default=dict)
    interval_seconds = models.PositiveIntegerField()
    next_run_at = models.DateTimeField(db_index=True)
    last_run_at = models.DateTimeField(null=True, blank=True)
    active = models.BooleanField(default=True, db_index=True)
