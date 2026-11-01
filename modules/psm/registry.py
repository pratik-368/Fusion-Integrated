from modules.psm.permissions import PERMISSIONS, ROLE_GRANTS  # noqa: F401

MODULE = {
    "code": "psm",
    "label": "Purchase & Stores",
    "icon": "FaBoxes",
    "base_path": "/psm",
    "nav_section": "Administration",
    "sort_order": 40,
    "status": "active",
}

NAV_ITEMS = [
    {
        "code": "psm.my_indents",
        "label": "My Indents",
        "icon": "FaClipboardList",
        "to": "/psm/indents/mine",
        "required_permission": "psm.indent.view_self",
        "sort_order": 10,
    },
    {
        "code": "psm.indents",
        "label": "Indent Queue",
        "icon": "FaInbox",
        "to": "/psm/indents",
        "required_permission": "psm.indent.view",
        "sort_order": 20,
    },
    {
        "code": "psm.inventory",
        "label": "Inventory",
        "icon": "FaBoxes",
        "to": "/psm/inventory",
        "required_permission": "psm.stock.view",
        "sort_order": 30,
    },
    {
        "code": "psm.vendors",
        "label": "Vendors",
        "icon": "FaTruck",
        "to": "/psm/vendors",
        "required_permission": "psm.vendor.view",
        "sort_order": 40,
    },
    {
        "code": "psm.procurement",
        "label": "Procurement",
        "icon": "FaFileInvoice",
        "to": "/psm/purchase-orders",
        "required_permission": "psm.procurement.manage",
        "sort_order": 50,
    },
    {
        "code": "psm.reports",
        "label": "Reports",
        "icon": "FaChartBar",
        "to": "/psm/reports",
        "required_permission": "psm.report.view",
        "sort_order": 60,
    },
]
