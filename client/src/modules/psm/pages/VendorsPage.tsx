import { useState } from "react";
import { Button, Group, Stack, Table, Text, TextInput } from "@mantine/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { notifications } from "@mantine/notifications";
import { http, errorMessage } from "../../../lib/http";
import { PageHeader } from "../../../ui/components/PageHeader";
import { StatusBadge } from "../../../ui/components/StatusBadge";

type Vendor = { id: number; name: string; contact_email: string; gst_number: string; bank_details: Record<string, string>;
  compliance_documents: { type: string; reference: string }[]; verified: boolean };
export default function VendorsPage() {
  const [form, setForm] = useState({ name: "", contact_email: "", gst_number: "", bank_name: "",
    account_number: "", ifsc: "", document_type: "", document_reference: "" });
  const client = useQueryClient();
  const query = useQuery({ queryKey: ["psm", "vendors"],
    queryFn: async () => (await http.get<Vendor[]>("/psm/vendors")).data });
  const create = useMutation({ mutationFn: async () => (await http.post("/psm/vendors", {
    name: form.name, contact_email: form.contact_email, gst_number: form.gst_number,
    bank_details: { bank_name: form.bank_name, account_number: form.account_number, ifsc: form.ifsc },
    compliance_documents: [{ type: form.document_type, reference: form.document_reference }],
  })).data, onSuccess: () => { setForm({ name: "", contact_email: "", gst_number: "", bank_name: "",
    account_number: "", ifsc: "", document_type: "", document_reference: "" });
    void client.invalidateQueries({ queryKey: ["psm", "vendors"] }); },
  onError: (e) => notifications.show({ color: "red", title: "Could not save vendor", message: errorMessage(e) }) });
  const verify = useMutation({ mutationFn: async (id: number) => http.post(`/psm/vendors/${id}/verify`, {}),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["psm", "vendors"] }),
    onError: (e) => notifications.show({ color: "red", title: "Could not verify vendor", message: errorMessage(e) }) });
  const set = (key: keyof typeof form, value: string) => setForm((current) => ({ ...current, [key]: value }));
  return <Stack><PageHeader title="Vendors" subtitle="Onboard vendors and validate their master records" />
    {query.isError && <Text c="red">{errorMessage(query.error)}</Text>}
    <Stack gap="xs"><Group grow>{(["name", "contact_email", "gst_number", "bank_name"] as const).map((key) =>
      <TextInput key={key} label={key.replaceAll("_", " ")} value={form[key]} onChange={(e) => set(key, e.currentTarget.value)} />)}</Group>
      <Group grow>{(["account_number", "ifsc", "document_type", "document_reference"] as const).map((key) =>
        <TextInput key={key} label={key.replaceAll("_", " ")} value={form[key]} onChange={(e) => set(key, e.currentTarget.value)} />)}</Group>
      <Group justify="flex-end"><Button loading={create.isPending} onClick={() => create.mutate()}>Add vendor</Button></Group></Stack>
    <Table striped><Table.Thead><Table.Tr><Table.Th>Name</Table.Th><Table.Th>GSTIN</Table.Th>
      <Table.Th>Bank</Table.Th><Table.Th>Verification</Table.Th><Table.Th /></Table.Tr></Table.Thead>
      <Table.Tbody>{(query.data ?? []).map((vendor) => <Table.Tr key={vendor.id}>
        <Table.Td>{vendor.name}</Table.Td><Table.Td>{vendor.gst_number}</Table.Td>
        <Table.Td>{vendor.bank_details.bank_name}</Table.Td><Table.Td><StatusBadge status={vendor.verified ? "verified" : "pending"} /></Table.Td>
        <Table.Td>{!vendor.verified && <Button size="xs" variant="light" loading={verify.isPending}
          onClick={() => verify.mutate(vendor.id)}>Verify</Button>}</Table.Td>
      </Table.Tr>)}</Table.Tbody></Table>
  </Stack>;
}
