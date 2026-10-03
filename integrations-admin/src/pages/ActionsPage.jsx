import ActionRow from "../components/ActionRow";
import { Empty, ErrorBox, Loading } from "../components/States";
import { useActions } from "../hooks/useActions";

export default function ActionsPage({ api }) {
  const { status, data, error, reload, save } = useActions(api);
  if (status === "loading") return <Loading />;
  if (status === "error") return <ErrorBox error={error} onRetry={reload} />;
  if (!data.length) return <Empty>No actions defined.</Empty>;
  return (
    <>
      <p className="muted">Expand a row to see its input schema and change retry limits.</p>
      <table>
        <thead><tr><th>Action</th><th>Type</th><th>Max attempts</th></tr></thead>
        <tbody>{data.map((a) => <ActionRow key={a.action} action={a} onSave={save} />)}</tbody>
      </table>
    </>
  );
}
