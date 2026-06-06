// Adds custom matchers like toBeInTheDocument() for React Testing Library.
import "@testing-library/jest-dom";

// jsdom lacks ResizeObserver, which Recharts' ResponsiveContainer requires.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
// eslint-disable-next-line @typescript-eslint/no-explicit-any
(global as any).ResizeObserver = (global as any).ResizeObserver || ResizeObserverStub;
