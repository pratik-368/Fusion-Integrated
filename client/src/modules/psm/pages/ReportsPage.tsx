import { Button, Stack, Table, Text } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { http, errorMessage } from "../../../lib/http";
import { PageHeader } from "../../../ui/components/PageHeader";

export default function ReportsPage() {
  const query = useQuery({ queryKey: ["psm", "dashboard"],
    queryFn: async () => (await http.get<Record<string, unknown>>("/psm/dashboard")).data });
  return <Stack><PageHeader title="Purchase and stores dashboard"
    subtitle="Current indent, inventory, procurement, and invoice metrics"
    action={<Button component="a" href="/api/v1/psm/reports/indents.csv">Export indents CSV</Button>} />
    {query.isError && <Text c="red">{errorMessage(query.error)}</Text>}
    <Table striped><Table.Thead><Table.Tr><Table.Th>Metric</Table.Th><Table.Th>Value</Table.Th></Table.Tr></Table.Thead>
      <Table.Tbody>{Object.entries(query.data ?? {}).map(([key, value]) => <Table.Tr key={key}>
        <Table.Td>{key.replaceAll("_", " ")}</Table.Td>
        <Table.Td>{Array.isArray(value) ? value.map((row) => JSON.stringify(row)).join(" · ") : String(value)}</Table.Td>
      </Table.Tr>)}</Table.Tbody></Table>
  </Stack>;
}
