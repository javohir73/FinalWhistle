// Adds custom matchers like toBeInTheDocument() for React Testing Library.
import "@testing-library/jest-dom";

// jsdom's crypto shim lacks randomUUID (a real browser has it), used by
// lib/session.ts's getOrCreateDeviceId(). Node itself has a working one.
if (typeof crypto !== "undefined" && typeof crypto.randomUUID !== "function") {
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  const nodeCrypto = require("node:crypto");
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (crypto as any).randomUUID = () => nodeCrypto.randomUUID();
}

// jsdom lacks ResizeObserver, which Recharts' ResponsiveContainer requires.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
// eslint-disable-next-line @typescript-eslint/no-explicit-any
(global as any).ResizeObserver = (global as any).ResizeObserver || ResizeObserverStub;

// jsdom lacks IntersectionObserver, used by the scroll-reveal component.
class IntersectionObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
  takeRecords() {
    return [];
  }
}
// eslint-disable-next-line @typescript-eslint/no-explicit-any
(global as any).IntersectionObserver =
  (global as any).IntersectionObserver || IntersectionObserverStub;
