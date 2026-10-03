import { fireEvent, render, screen } from "@testing-library/react";
import ConfirmDialog from "./ConfirmDialog";

test("confirm and cancel call their handlers", () => {
  const onConfirm = vi.fn(), onCancel = vi.fn();
  render(<ConfirmDialog title="Switch?" confirmLabel="Do it" onConfirm={onConfirm} onCancel={onCancel}>impact</ConfirmDialog>);
  fireEvent.click(screen.getByText("Cancel"));
  expect(onCancel).toHaveBeenCalled();
  expect(onConfirm).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText("Do it"));
  expect(onConfirm).toHaveBeenCalled();
});
