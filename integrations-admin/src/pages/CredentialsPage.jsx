import CredentialsPanel from "../components/CredentialsPanel";
import { Empty, ErrorBox, Loading } from "../components/States";
import { useCredentials } from "../hooks/useCredentials";

export default function CredentialsPage({ api }) {
  const { status, data, error, reload, save, clear } = useCredentials(api);
  if (status === "loading") return <Loading />;
  if (status === "error") return <ErrorBox error={error} onRetry={reload} />;
  if (!data.length) return <Empty>No credentials defined.</Empty>;
  return (
    <>
      <CredentialsPanel credentials={data} onSave={save} onClear={clear} />
    </>
  );
}
