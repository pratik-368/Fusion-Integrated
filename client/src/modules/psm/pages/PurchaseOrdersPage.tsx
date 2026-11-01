import ResourcePage from "./ResourcePage";
export default function PurchaseOrdersPage() {
  return <ResourcePage title="Purchase orders" endpoint="purchase-orders"
    fields={["id", "indent", "vendor", "po_number", "status", "total_amount"]} />;
}
