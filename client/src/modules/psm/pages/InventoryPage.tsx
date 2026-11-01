import ResourcePage from "./ResourcePage";
export default function InventoryPage() {
  return <ResourcePage title="Inventory" endpoint="inventory"
    fields={["item_code", "description", "location_id", "department_id", "quantity_on_hand"]} editable />;
}
