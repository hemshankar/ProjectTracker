import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import ActionRow from "./ActionRow";

const base = { action: "slack.list_channels", mutating: false, description: "List", inputSchema: { type: "object" },
  maxAttempts: 3, baseDelayMs: 500, retriesEditable: true };
const wrap = (a, onSave) => render(<table><tbody><ActionRow action={a} onSave={onSave} /></tbody></table>);

test("saves edited retry settings", async () => {
  const onSave = vi.fn().mockResolvedValue();
  wrap(base, onSave);
  fireEvent.click(screen.getByRole("button", { name: /slack\.list_channels/ }));
  fireEvent.change(screen.getByLabelText(/Max attempts/), { target: { value: "5" } });
  fireEvent.click(screen.getByText("Save"));
  await waitFor(() => expect(onSave).toHaveBeenCalledWith("slack.list_channels", { baseDelayMs: 500, maxAttempts: 5 }));
});

test("write actions: retries locked", () => {
  wrap({ ...base, action: "slack.post_message", mutating: true, retriesEditable: false, maxAttempts: 1 }, vi.fn());
  fireEvent.click(screen.getByRole("button", { name: /slack\.post_message/ }));
  expect(screen.getByLabelText(/Max attempts/).disabled).toBe(true);
});
