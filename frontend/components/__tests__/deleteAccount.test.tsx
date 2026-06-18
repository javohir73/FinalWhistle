/** Account deletion flow from the account menu → confirm dialog (Apple 5.1.1(v)). */
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { AccountMenu } from "@/components/AccountMenu";
import { ApiError, type SessionUser } from "@/lib/session";

const user: SessionUser = {
  id: 1,
  email: "pat@example.com",
  display_name: "Pat",
  avatar_url: null,
};

function openDeleteDialog() {
  fireEvent.click(screen.getByRole("button", { name: /account: pat/i }));
  fireEvent.click(screen.getByRole("menuitem", { name: /delete account/i }));
}

it("confirms with the password and calls the delete handler", async () => {
  const onDeleteAccount = jest.fn().mockResolvedValue(undefined);
  render(<AccountMenu user={user} onLogout={() => {}} onDeleteAccount={onDeleteAccount} />);

  openDeleteDialog();
  fireEvent.change(screen.getByLabelText(/password/i), { target: { value: "supersecret" } });
  fireEvent.click(screen.getByRole("button", { name: /^delete account$/i }));

  await waitFor(() => expect(onDeleteAccount).toHaveBeenCalledWith("supersecret"));
});

it("surfaces the server error when the password is wrong", async () => {
  const onDeleteAccount = jest
    .fn()
    .mockRejectedValue(new ApiError(401, "invalid_credentials", "Current password is incorrect."));
  render(<AccountMenu user={user} onLogout={() => {}} onDeleteAccount={onDeleteAccount} />);

  openDeleteDialog();
  fireEvent.change(screen.getByLabelText(/password/i), { target: { value: "wrong" } });
  fireEvent.click(screen.getByRole("button", { name: /^delete account$/i }));

  expect(await screen.findByRole("alert")).toHaveTextContent(/incorrect/i);
});
