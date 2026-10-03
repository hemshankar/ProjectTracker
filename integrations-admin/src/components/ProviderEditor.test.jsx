import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import ProviderEditor from "./ProviderEditor";

const provider = { toolType: "slack", displayName: "Slack", backend: "composio", backendSlug: "slack" };

test("a 409 shows the connection count and only confirm applies the switch", async () => {
  const onSave = vi.fn()
    .mockRejectedValueOnce(Object.assign(new Error("x"), { status: 409, detail: { connectionsAffected: 3 } }))
    .mockResolvedValueOnce({});
  const onClose = vi.fn();
  render(<ProviderEditor provider={provider} onSave={onSave} onClose={onClose} />);
  fireEvent.change(screen.getByLabelText("Backend"), { target: { value: "nango" } });
  fireEvent.click(screen.getByText("Save"));
  await screen.findByText(/will disconnect/);
  expect(screen.getByText("3")).toBeTruthy();
  expect(onClose).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText(/Disconnect 3 and switch/));
  await waitFor(() => expect(onSave).toHaveBeenLastCalledWith("slack", expect.objectContaining({ confirm: true, backend: "nango" })));
  await waitFor(() => expect(onClose).toHaveBeenCalled());
});
