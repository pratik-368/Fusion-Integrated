import { useState } from "react";
import {
  Button, Card, Container, Group, Modal, Select, Stack, Text, TextInput,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { FaClipboardList } from "react-icons/fa";

import { errorMessage } from "../../../lib/http";
import { DataTable } from "../../../ui/components/DataTable";
import { ErrorState } from "../../../ui/components/ErrorState";
import { PageHeader } from "../../../ui/components/PageHeader";
import { StatusBadge } from "../../../ui/components/StatusBadge";
import { useLeaveRecords, useRecordOffline } from "../api/hooks";
import type { LeaveRequest } from "../api/types";
import { CATEGORY_LABELS } from "../api/types";

const CATEGORY_OPTIONS = Object.entries(CATEGORY_LABELS)
  .map(([value, label]) => ({ value, label }));

const STATUS_OPTIONS = [
  { value: "", label: "Any status" },
  { value: "draft", label: "Draft" },
  { value: "approved", label: "Approved" },
  { value: "extended", label: "Extended" },
  { value: "rejected", label: "Rejected" },
  { value: "withdrawn", label: "Withdrawn" },
  { value: "cancelled", label: "Cancelled" },
];

/** EL-UC-016: leave already sanctioned on paper is recorded, not re-approved. */
function OfflineRecordModal({ opened, onClose }: {
  opened: boolean;
  onClose: () => void;
}) {
  const [employeeId, setEmployeeId] = useState("");
  const [category, setCategory] = useState("cl");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [evidence, setEvidence] = useState("");
  const [certifiedBy, setCertifiedBy] = useState("");

  const record = useRecordOffline();

  function submit() {
    record.mutate({
      employee_user_id: Number(employeeId),
      category,
      period_from: from,
      period_to: to || from,
      evidence_reference: evidence,
      certified_by: certifiedBy,
    }, {
      onSuccess: () => {
        notifications.show({
          color: "green", title: "Recorded",
          message: "The offline sanction has been added to the employee's account.",
        });
        setEmployeeId("");
        setFrom("");
        setTo("");
        setEvidence("");
        setCertifiedBy("");
        onClose();
      },
      onError: (e) => notifications.show({
        color: "red", title: "Could not record", message: errorMessage(e),
      }),
    });
  }

  return (
    <Modal opened={opened} onClose={onClose} title="Record offline-sanctioned leave">
      <Stack>
        <TextInput
          label="Employee id" value={employeeId}
          onChange={(e) => setEmployeeId(e.currentTarget.value)}
        />
        <Select
          label="Leave category" data={CATEGORY_OPTIONS} value={category}
          onChange={(v) => setCategory(v ?? "cl")} allowDeselect={false}
        />
        <Group grow>
          <TextInput
            type="date" label="From" value={from}
            onChange={(e) => setFrom(e.currentTarget.value)}
          />
          <TextInput
            type="date" label="To" value={to}
            onChange={(e) => setTo(e.currentTarget.value)}
          />
        </Group>
        <TextInput
          label="Sanction / evidence reference" required value={evidence}
          onChange={(e) => setEvidence(e.currentTarget.value)}
        />
        <TextInput
          label="Certified by" value={certifiedBy}
          onChange={(e) => setCertifiedBy(e.currentTarget.value)}
        />
        <Group justify="flex-end">
          <Button
            loading={record.isPending}
            disabled={!employeeId || !from || !evidence}
            onClick={submit}
          >
            Record
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

export default function RecordsPage() {
  const [category, setCategory] = useState("");
  const [status, setStatus] = useState("");
  const [recording, setRecording] = useState(false);

  const records = useLeaveRecords({ category, status });
  const rows = records.data?.results ?? [];

  if (records.error) {
    return <Container size="xl"><ErrorState error={records.error} /></Container>;
  }

  return (
    <Container size="xl">
      <PageHeader
        title="Leave Records"
        subtitle="Every recorded leave, including sanctions synchronised from paper"
        action={
          <Button onClick={() => setRecording(true)}>Record offline leave</Button>
        }
      />

      <Card withBorder padding="md" mb="md">
        <Group gap="md" wrap="wrap">
          <Select
            label="Category" data={[{ value: "", label: "Any category" },
                                   ...CATEGORY_OPTIONS]}
            value={category} onChange={(v) => setCategory(v ?? "")}
            allowDeselect={false}
          />
          <Select
            label="Status" data={STATUS_OPTIONS} value={status}
            onChange={(v) => setStatus(v ?? "")} allowDeselect={false}
          />
        </Group>
      </Card>

      <Card withBorder padding="lg">
        <DataTable<LeaveRequest>
          rows={rows}
          loading={records.isPending}
          rowKey={(r) => r.id}
          minWidth={900}
          columns={[
            { key: "reference", header: "Reference",
              render: (r) => <Text size="sm">{r.reference ?? `#${r.id}`}</Text> },
            { key: "employee", header: "Employee",
              render: (r) => `u${r.user_id}` },
            { key: "category", header: "Category",
              render: (r) => r.category_label },
            { key: "period", header: "Period",
              render: (r) => `${r.period_from} → ${r.period_to}` },
            { key: "days", header: "Days", render: (r) => r.days_counted },
            { key: "source", header: "Source", render: (r) => r.source },
            { key: "status", header: "Status",
              render: (r) => <StatusBadge status={r.status} /> },
          ]}
          empty={{
            icon: FaClipboardList, title: "No leave records",
            description: "Every recorded sanction and application appears here.",
          }}
        />
      </Card>

      <OfflineRecordModal opened={recording} onClose={() => setRecording(false)} />
    </Container>
  );
}
