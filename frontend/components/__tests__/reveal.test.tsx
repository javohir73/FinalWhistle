/** Scroll-reveal: content already on screen at mount (e.g. a tab panel that
 *  just swapped in client-side) must show immediately, not wait on the
 *  IntersectionObserver's async first callback — which is what left the AI
 *  bracket's on-screen rounds stuck at opacity:0 on load. */
import { render, screen } from "@testing-library/react";
import { Reveal } from "@/components/Reveal";

const setRect = (rect: Partial<DOMRect>) => {
  HTMLElement.prototype.getBoundingClientRect = jest.fn(() => ({
    top: 0,
    bottom: 0,
    left: 0,
    right: 0,
    width: 0,
    height: 0,
    x: 0,
    y: 0,
    toJSON() {},
    ...rect,
  }));
};

afterEach(() => {
  jest.restoreAllMocks();
});

it("is visible immediately when already within the viewport at mount", () => {
  setRect({ top: 100, bottom: 200 });
  render(
    <Reveal>
      <p>On screen</p>
    </Reveal>,
  );
  expect(screen.getByText("On screen").parentElement).toHaveClass("is-visible");
});

it("stays hidden at mount when below the fold, awaiting the scroll-reveal observer", () => {
  setRect({ top: 5000, bottom: 5100 });
  render(
    <Reveal>
      <p>Below fold</p>
    </Reveal>,
  );
  expect(screen.getByText("Below fold").parentElement).not.toHaveClass("is-visible");
});
