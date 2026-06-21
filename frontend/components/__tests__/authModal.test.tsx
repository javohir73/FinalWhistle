/** The password field offers a show/hide toggle — fewer sign-in failures on a
 *  key conversion surface, especially on mobile. */
import { render, screen, fireEvent } from "@testing-library/react";
import { AuthModal } from "@/components/AuthModal";

it("toggles password visibility and reflects state via aria-pressed", () => {
  render(<AuthModal open onClose={() => {}} onAuthed={() => {}} />);

  const pwd = screen.getByLabelText("Password") as HTMLInputElement;
  expect(pwd.type).toBe("password");

  fireEvent.click(screen.getByRole("button", { name: "Show password" }));
  expect(pwd.type).toBe("text");

  const hide = screen.getByRole("button", { name: "Hide password" });
  expect(hide).toHaveAttribute("aria-pressed", "true");

  fireEvent.click(hide);
  expect(pwd.type).toBe("password");
  expect(screen.getByRole("button", { name: "Show password" })).toHaveAttribute("aria-pressed", "false");
});
