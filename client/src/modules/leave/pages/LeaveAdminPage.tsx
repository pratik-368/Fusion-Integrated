import { useState } from "react";
import { Badge, Card, Container, Group, Stack, Tabs, Text } from "@mantine/core";
import {
  FaCalendarAlt, FaClipboardList, FaCog, FaExchangeAlt, FaHistory,
} from "react-icons/fa";

import { DataTable } from "../../../ui/components/DataTable";
import { ErrorState } from "../../../ui/components/ErrorState";
import { PageHeader } from "../../../ui/components/PageHeader";
import {
  useCalendars, useHierarchy, usePolicy, useSlaThresholds,
} from "../api/hooks";
import type {
  HierarchyRule, HolidayCalendar, LeavePolicy, SlaThreshold,
} from "../api/types";

type Tab = "policy" | "hierarchy" | "calendar" | "sla";

function PolicyTable() {
  const { data, isPending } = usePolicy();
  return (
    <DataTable<LeavePolicy>
      rows={data?.results ?? []}
      loading={isPending}
      rowKey={(r) => r.id}
      minWidth={700}
      columns={[
        { key: "year", header: "Leave year", render: (r) => r.leave_year },
        { key: "label", header: "Label", render: (r) => r.label },
        { key: "current", header: "In force",
          render: (r) => (r.is_current ? "Yes" : "No") },
        { key: "entitlements", header: "Entitlements",
          render: (r) => Object.entries(r.entitlements)
            .map(([category, days]) => `${category} ${days}`).join(" · ") },
        { key: "year_end", header: "Year end",
          render: (r) => `${r.year_end_day}/${r.year_end_month}` },
      ]}
      empty={{
        icon: FaCog, title: "No policy configured",
        description: "The current policy appears here once an administrator saves one.",
      }}
    />
  );
}

function HierarchyTable() {
  const { data, isPending } = useHierarchy();
  return (
    <DataTable<HierarchyRule>
      rows={data?.results ?? []}
      loading={isPending}
      rowKey={(r) => `${r.category}-${r.step_order}`}
      minWidth={800}
      columns={[
        { key: "category", header: "Category",
          render: (r) => r.category || "Any" },
        { key: "order", header: "Step", render: (r) => r.step_order },
        { key: "kind", header: "Kind",
          render: (r) => <Badge variant="light">{r.step_kind}</Badge> },
        { key: "authority", header: "Authority",
          render: (r) => r.authority || "—" },
        { key: "label", header: "Label", render: (r) => r.label || "—" },
      ]}
      empty={{
        icon: FaHistory, title: "No hierarchy configured",
        description: "Every request falls back to the Unit Head and Registrar.",
      }}
    />
  );
}

function CalendarTable() {
  const { data, isPending } = useCalendars();
  return (
    <DataTable<HolidayCalendar>
      rows={data?.results ?? []}
      loading={isPending}
      rowKey={(r) => r.id}
      minWidth={700}
      columns={[
        { key: "year", header: "Leave year", render: (r) => r.leave_year },
        { key: "label", header: "Label", render: (r) => r.label },
        { key: "published", header: "Published",
          render: (r) => (r.published_at ? "Yes" : "No") },
        { key: "effective", header: "Governing",
          render: (r) => (r.is_effective ? "Yes" : "No") },
        { key: "entries", header: "Entries", render: (r) => r.entries.length },
      ]}
      empty={{
        icon: FaCalendarAlt, title: "No holiday calendar",
        description: "A published calendar is what a Restricted Holiday is checked against.",
      }}
    />
  );
}

function SlaTable() {
  const { data, isPending } = useSlaThresholds();
  return (
    <DataTable<SlaThreshold>
      rows={data?.results ?? []}
      loading={isPending}
      rowKey={(r) => r.id}
      minWidth={720}
      columns={[
        { key: "task", header: "Task class", render: (r) => r.task_class },
        { key: "reminder", header: "Remind after",
          render: (r) => `${r.reminder_hours}h` },
        { key: "escalation", header: "Escalate after",
          render: (r) => `${r.escalation_hours}h` },
        { key: "action", header: "Escalation",
          render: (r) => r.escalation_action },
        { key: "role", header: "Reassign to",
          render: (r) => r.escalate_to_role || "—" },
      ]}
      empty={{
        icon: FaExchangeAlt, title: "No SLA thresholds",
        description: "Tasks are reminded and escalated once a threshold is configured.",
      }}
    />
  );
}

export default function LeaveAdminPage() {
  const policy = usePolicy();
  const hierarchy = useHierarchy();
  const calendars = useCalendars();
  const sla = useSlaThresholds();
  const [tab, setTab] = useState<Tab>("policy");

  const error = policy.error ?? hierarchy.error ?? calendars.error ?? sla.error;
  if (error) {
    return <Container size="xl"><ErrorState error={error} /></Container>;
  }

  return (
    <Container size="xl">
      <PageHeader
        title="Leave Administration"
        subtitle="The policy, hierarchy, holiday calendar and service levels currently in force"
        action={<Badge variant="light">Read-only</Badge>}
      />

      <Card withBorder padding="lg">
        <Group justify="space-between" mb="md">
          <Stack gap={0}>
            <Text fw={600}>Configuration</Text>
            <Text size="sm" c="dimmed">
              Changes are made through the administration API.
            </Text>
          </Stack>
          <Tabs value={tab} onChange={(v) => setTab(v as Tab)}>
            <Tabs.List>
              <Tabs.Tab value="policy" leftSection={<FaClipboardList size={12} />}>
                Policy
              </Tabs.Tab>
              <Tabs.Tab value="hierarchy" leftSection={<FaHistory size={12} />}>
                Hierarchy
              </Tabs.Tab>
              <Tabs.Tab value="calendar" leftSection={<FaCalendarAlt size={12} />}>
                Calendar
              </Tabs.Tab>
              <Tabs.Tab value="sla" leftSection={<FaExchangeAlt size={12} />}>
                SLA
              </Tabs.Tab>
            </Tabs.List>
          </Tabs>
        </Group>

        {tab === "policy" && <PolicyTable />}
        {tab === "hierarchy" && <HierarchyTable />}
        {tab === "calendar" && <CalendarTable />}
        {tab === "sla" && <SlaTable />}
      </Card>
    </Container>
  );
}
