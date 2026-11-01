# Purchase and Stores Management (PSM)

PSM is an independently registered module. Its people references are scalar IAM IDs; its records, lifecycle rules, audit events, and inventory ledgers are owned by `modules.psm`.

## Policy setup

The supplied P&S baseline leaves these values unspecified. Configure them through the authenticated `PUT /api/v1/psm/policies` endpoint before using the related flows; the service intentionally refuses to guess them.

- `tender_threshold`: decimal amount at or above which tender procurement applies.
- `approval_hierarchy`: object with `department_head_required` (boolean) and `final_approval_threshold` (decimal amount).
- `modifiable_indent_states`, `withdrawable_indent_states`, and `cancellable_indent_states`: arrays of allowed indent status values.
- `required_vendor_documents`: array of compliance document type identifiers.

Example request bodies use `{"key": "tender_threshold", "value": "<approved decimal>"}` and `{"key": "approval_hierarchy", "value": {"department_head_required": true, "final_approval_threshold": "<approved decimal>"}}`; replace the placeholders with approved institutional values.

## Lifecycle API

- `POST /indents`, `POST /indents/{id}/submit`, `/stock-check`, `/decision`, `/modify`, `/repeat`, `/withdraw`, `/cancel`, `/history`
- `GET|POST /inventory`, `GET|POST /vendors`, `PUT /vendors/{id}`, `POST /vendors/{id}/verify`
- `GET|POST /tenders`, `POST /tenders/{id}/publish|bids|award`, `GET|POST /purchase-orders`
- `GET|POST /goods-receipts`, `POST /goods-receipts/{id}/confirm`, `GET|POST /discrepancies`, `POST /discrepancies/{id}/resolve`
- `GET|POST /invoices`, `POST /invoices/{id}/verify`, `POST /invoices/{id}/payments`
- `GET|POST /stock-transfers`, `POST /stock-transfers/{id}/dispatch|receive`
- `GET /dashboard`, `GET /reports/indents.csv`, `GET|POST /report-schedules`, `DELETE /report-schedules/{id}`, `GET /audit`

All routes are mounted beneath `/api/v1/psm/` and use module grants plus action permissions. Receipt and transfer ledgers are posted transactionally; audit rows are append-only application records.

Run `manage.py run_psm_reports` from the deployment scheduler at the cadence configured by operations. Each due schedule creates a report run and audit event; its interval and next run are set by the report owner. Run `manage.py send_psm_notifications` from the mail worker to deliver queued lifecycle notifications. Both commands use the configured Django email backend.
