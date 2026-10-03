import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import CredentialsPanel from "./CredentialsPanel";

const cred = { name: "composio_api_key", label: "Composio API key", status: "set", source: "db" };

test("input is a write-only password field and is cleared after save", async () => {
  const onSave = vi.fn().mockResolvedValue();
  render(<CredentialsPanel credentials={[cred]} onSave={onSave} onClear={vi.fn()} />);
  const input = screen.getByLabelText("Composio API key");
  expect(input.type).toBe("password");
  expect(input.autocomplete).toBe("off");
  expect(input.value).toBe(""); // existing value is never rendered
  fireEvent.change(input, { target: { value: "new-secret" } });
  fireEvent.click(screen.getByText("Rotate"));
  await waitFor(() => expect(onSave).toHaveBeenCalledWith("composio_api_key", "new-secret"));
  await waitFor(() => expect(input.value).toBe(""));
});
