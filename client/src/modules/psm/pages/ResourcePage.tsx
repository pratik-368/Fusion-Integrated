import { useState } from "react";
import { Button, Group, Stack, Table, Text, TextInput } from "@mantine/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { notifications } from "@mantine/notifications";
import { http, errorMessage } from "../../../lib/http";
import { PageHeader } from "../../../ui/components/PageHeader";

type Props = { title: string; endpoint: string; fields: string[]; editable?: boolean };
export default function ResourcePage({ title, endpoint, fields, editable = false }: Props) {
  const [values, setValues] = useState<Record<string, string>>({});
  const client = useQueryClient();
  const query = useQuery({ queryKey: ["psm", endpoint],
    queryFn: async () => (await http.get<unknown[]>(`/psm/${endpoint}`)).data });
  const create = useMutation({ mutationFn: async () => (await http.post(`/psm/${endpoint}`, values)).data,
    onSuccess: () => { setValues({}); void client.invalidateQueries({ queryKey: ["psm", endpoint] }); },
    onError: (e) => notifications.show({ color: "red", title: "Could not save", message: errorMessage(e) }) });
  const rows = query.data ?? [];
  return <Stack><PageHeader title={title} subtitle="Purchase and stores records" />
    {query.isError && <Text c="red">{errorMessage(query.error)}</Text>}
    {editable && <Group align="end">{fields.map((field) => <TextInput key={field} label={field.replaceAll("_", " ")}
      value={values[field] ?? ""} onChange={(e) => setValues({ ...values, [field]: e.currentTarget.value })} />)}
      <Button loading={create.isPending} onClick={() => create.mutate()}>Add</Button></Group>}
    <Table striped><Table.Thead><Table.Tr>{fields.map((f) => <Table.Th key={f}>{f.replaceAll("_", " ")}</Table.Th>)}</Table.Tr></Table.Thead>
      <Table.Tbody>{rows.map((row, i) => <Table.Tr key={i}>{fields.map((f) => <Table.Td key={f}>{String((row as Record<string, unknown>)[f] ?? "—")}</Table.Td>)}</Table.Tr>)}</Table.Tbody></Table>
  </Stack>;
}
