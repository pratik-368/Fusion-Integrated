from django.urls import path

from modules.psm.api import views

urlpatterns = [
    path("indents", views.IndentCollectionView.as_view(), name="psm-indents"),
    path("indents/<int:pk>/history", views.IndentHistoryView.as_view(), name="psm-indent-history"),
    path(
        "indents/<int:pk>/<str:action>", views.IndentActionView.as_view(), name="psm-indent-action"
    ),
    path("inventory", views.InventoryView.as_view(), name="psm-inventory"),
    path("vendors", views.VendorCollectionView.as_view(), name="psm-vendors"),
    path("vendors/<int:pk>/verify", views.VendorVerifyView.as_view(), name="psm-vendor-verify"),
    path("vendors/<int:pk>", views.VendorUpdateView.as_view(), name="psm-vendor-update"),
    path(
        "purchase-orders", views.PurchaseOrderCollectionView.as_view(), name="psm-purchase-orders"
    ),
    path("goods-receipts", views.GoodsReceiptView.as_view(), name="psm-goods-receipts"),
    path(
        "goods-receipts/<int:pk>/confirm",
        views.GoodsReceiptConfirmView.as_view(),
        name="psm-goods-receipt-confirm",
    ),
    path("invoices", views.InvoiceCollectionView.as_view(), name="psm-invoices"),
    path("invoices/<int:pk>/verify", views.InvoiceVerifyView.as_view(), name="psm-invoice-verify"),
    path("invoices/<int:pk>/payments", views.PaymentView.as_view(), name="psm-payments"),
    path("tenders", views.TenderCollectionView.as_view(), name="psm-tenders"),
    path(
        "tenders/<int:pk>/<str:action>", views.TenderActionView.as_view(), name="psm-tender-action"
    ),
    path("discrepancies", views.DiscrepancyCollectionView.as_view(), name="psm-discrepancies"),
    path(
        "discrepancies/<int:pk>/resolve",
        views.DiscrepancyResolveView.as_view(),
        name="psm-discrepancy-resolve",
    ),
    path(
        "stock-transfers", views.StockTransferCollectionView.as_view(), name="psm-stock-transfers"
    ),
    path(
        "stock-transfers/<int:pk>/<str:action>",
        views.StockTransferActionView.as_view(),
        name="psm-stock-transfer-action",
    ),
    path("policies", views.PolicyView.as_view(), name="psm-policies"),
    path("dashboard", views.DashboardView.as_view(), name="psm-dashboard"),
    path("reports/indents.csv", views.ReportExportView.as_view(), name="psm-report-export"),
    path("report-schedules", views.ReportScheduleView.as_view(), name="psm-report-schedules"),
    path(
        "report-schedules/<int:pk>",
        views.ReportScheduleDetailView.as_view(),
        name="psm-report-schedule-detail",
    ),
    path("audit", views.AuditView.as_view(), name="psm-audit"),
    path("communications", views.CommunicationHistoryView.as_view(), name="psm-communications"),
]
