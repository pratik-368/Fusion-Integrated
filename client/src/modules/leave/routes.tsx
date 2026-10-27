import { lazy } from "react";
import { Navigate, type RouteObject } from "react-router-dom";

/** One lazy chunk per page. Vite can only split these if the import() argument
 *  is a static literal — a computed path silently bundles everything. */
const MyLeavePage = lazy(() => import("./pages/MyLeavePage"));
const ApprovalsPage = lazy(() => import("./pages/ApprovalsPage"));
const RecordsPage = lazy(() => import("./pages/RecordsPage"));
const LeaveAdminPage = lazy(() => import("./pages/LeaveAdminPage"));

/** Paths are RELATIVE — the shell mounts them under the manifest's basePath.
 *  Every entry here has a matching nav item in modules/leave/registry.py. */
export const routes: RouteObject[] = [
  { index: true, element: <Navigate to="mine" replace /> },
  { path: "mine", element: <MyLeavePage /> },
  { path: "approvals", element: <ApprovalsPage /> },
  { path: "records", element: <RecordsPage /> },
  { path: "admin", element: <LeaveAdminPage /> },
];
