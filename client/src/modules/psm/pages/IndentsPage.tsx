import { useState } from "react";
import { Button, Group, Modal, NumberInput, Stack, Table, Text, TextInput, Textarea } from "@mantine/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { notifications } from "@mantine/notifications";
import { http, errorMessage } from "../../../lib/http";
import { PageHeader } from "../../../ui/components/PageHeader";
import { StatusBadge } from "../../../ui/components/StatusBadge";

type Indent = { id: number; indent_number: string; status: string; justification: string;
  estimated_total: string; created_at: string; lines: { description: string; quantity: string }[] };
export default function IndentsPage({ scope }: { scope: "mine" | "queue" }) {
  const [opened, setOpened] = useState(false);
  const [justification, setJustification] = useState("");
  const [description, setDescription] = useState("");
  const [quantity, setQuantity] = useState<number | string>(1);
  const [cost, setCost] = useState<number | string>(0);
  const client = useQueryClient();
  const query = useQuery({ queryKey: ["psm", "indents", scope],
    queryFn: async () => (await http.get<Indent[]>("/psm/indents", {
      params: scope === "mine" ? { scope: "mine" } : {},
    })).data });
  const create = useMutation({ mutationFn: async () => (await http.post("/psm/indents", {
    justification,
    lines: [{ description, quantity: Number(quantity), estimated_unit_cost: Number(cost), item_code: "" }],
  })).data, onSuccess: () => { setOpened(false); setDescription(""); setJustification("");
    void client.invalidateQueries({ queryKey: ["psm", "indents"] }); },
  onError: (e) => notifications.show({ color: "red", title: "Could not create indent", message: errorMessage(e) }) });
  const action = useMutation({ mutationFn: async ({ id, name }: { id: number; name: string }) =>
    (await http.post(`/psm/indents/${id}/${name}`, {})).data,
    onSuccess: () => void client.invalidateQueries({ queryKey: ["psm", "indents"] }),
    onError: (e) => notifications.show({ color: "red", title: "Action failed", message: errorMessage(e) }) });
  const rows = query.data ?? [];
  return <Stack>
    <PageHeader title={scope === "mine" ? "My purchase indents" : "Indent review queue"}
      subtitle="Submit, track, and review institutional purchase requests."
      action={scope === "mine" ? <Button onClick={() => setOpened(true)}>New indent</Button> : undefined} />
    {query.isError && <Text c="red">{errorMessage(query.error)}</Text>}
    <Table striped highlightOnHover><Table.Thead><Table.Tr><Table.Th>Indent</Table.Th><Table.Th>Items</Table.Th>
      <Table.Th>Estimated total</Table.Th><Table.Th>Status</Table.Th><Table.Th>Actions</Table.Th></Table.Tr></Table.Thead>
      <Table.Tbody>{rows.map((item) => <Table.Tr key={item.id}><Table.Td>{item.indent_number}</Table.Td>
        <Table.Td>{item.lines.map((line) => `${line.description} × ${line.quantity}`).join(", ")}</Table.Td>
        <Table.Td>{item.estimated_total}</Table.Td><Table.Td><StatusBadge status={item.status} /></Table.Td>
        <Table.Td><Group gap="xs">{scope === "mine" && item.status === "draft" &&
          <Button size="xs" onClick={() => action.mutate({ id: item.id, name: "submit" })}>Submit</Button>}
          {scope === "queue" && item.status === "submitted" &&
          <Button size="xs" onClick={() => action.mutate({ id: item.id, name: "stock-check" })}>Check stock</Button>}</Group></Table.Td>
      </Table.Tr>)}</Table.Tbody></Table>
    <Modal opened={opened} onClose={() => setOpened(false)} title="Create purchase indent">
      <Stack><Textarea label="Justification" value={justification} onChange={(e) => setJustification(e.currentTarget.value)} required />
        <TextInput label="Item description" value={description} onChange={(e) => setDescription(e.currentTarget.value)} required />
        <Group grow><NumberInput label="Quantity" min={0.001} value={quantity} onChange={setQuantity} />
          <NumberInput label="Estimated unit cost" min={0} value={cost} onChange={setCost} /></Group>
        <Button loading={create.isPending} onClick={() => create.mutate()}>Save draft</Button></Stack>
    </Modal>
  </Stack>;
}
