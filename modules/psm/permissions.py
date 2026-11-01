MODULE_CODE = "psm"

PERMISSIONS = [
    ("psm.indent.view_self", "View own purchase indents"),
    ("psm.indent.view", "View purchase indents within role scope"),
    ("psm.indent.create", "Create and submit purchase indents"),
    ("psm.indent.review", "Review and approve purchase indents"),
    ("psm.indent.withdraw", "Withdraw or cancel eligible indents"),
    ("psm.stock.view", "View stock and reservations"),
    ("psm.stock.manage", "Manage stock, issues and transfers"),
    ("psm.vendor.view", "View vendor records"),
    ("psm.vendor.manage", "Onboard and maintain vendors"),
    ("psm.procurement.manage", "Manage tenders and purchase orders"),
    ("psm.tender.evaluate", "Evaluate tender bids and approve vendor selection"),
    ("psm.receipt.manage", "Inspect deliveries and record receipts"),
    ("psm.invoice.manage", "Verify invoices and process payments"),
    ("psm.report.view", "View authorized procurement and stores reports"),
    ("psm.audit.view", "View PSM audit records"),
]

ROLE_GRANTS = {
    "employee": ["psm.indent.view_self", "psm.indent.create", "psm.indent.withdraw"],
    "department_admin": [
        "psm.indent.view",
        "psm.indent.review",
        "psm.stock.view",
        "psm.stock.manage",
        "psm.receipt.manage",
    ],
    "department_head": [
        "psm.indent.view",
        "psm.indent.review",
        "psm.stock.view",
    ],
    "procurement_admin": [
        "psm.indent.view",
        "psm.indent.review",
        "psm.stock.view",
        "psm.stock.manage",
        "psm.vendor.view",
        "psm.vendor.manage",
        "psm.procurement.manage",
        "psm.receipt.manage",
        "psm.report.view",
    ],
    "procurement_committee": ["psm.tender.evaluate", "psm.indent.view", "psm.report.view"],
    "accounts_admin": [
        "psm.indent.view",
        "psm.vendor.view",
        "psm.invoice.manage",
        "psm.report.view",
    ],
    "director": ["psm.indent.view", "psm.indent.review", "psm.report.view"],
    "registrar": ["psm.indent.view", "psm.indent.review", "psm.report.view"],
    "auditor": [
        "psm.indent.view",
        "psm.stock.view",
        "psm.vendor.view",
        "psm.report.view",
        "psm.audit.view",
    ],
}
