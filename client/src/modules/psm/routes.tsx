import { lazy } from "react";
import { Navigate, type RouteObject } from "react-router-dom";

const IndentsPage = lazy(() => import("./pages/IndentsPage"));
const InventoryPage = lazy(() => import("./pages/InventoryPage"));
const VendorsPage = lazy(() => import("./pages/VendorsPage"));
const PurchaseOrdersPage = lazy(() => import("./pages/PurchaseOrdersPage"));
const ReportsPage = lazy(() => import("./pages/ReportsPage"));

export const routes: RouteObject[] = [
  { index: true, element: <Navigate to="indents/mine" replace /> },
  { path: "indents/mine", element: <IndentsPage scope="mine" /> },
  { path: "indents", element: <IndentsPage scope="queue" /> },
  { path: "inventory", element: <InventoryPage /> },
  { path: "vendors", element: <VendorsPage /> },
  { path: "purchase-orders", element: <PurchaseOrdersPage /> },
  { path: "reports", element: <ReportsPage /> },
];
