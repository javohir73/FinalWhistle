"use client";

import { ClerkProvider } from "@clerk/clerk-react";
import { CLERK_ENABLED, CLERK_PUBLISHABLE_KEY } from "@/lib/auth";

/** Wraps the app in Clerk only when a publishable key is configured. Without it,
 *  children render normally and no Clerk hook/component is ever mounted, so the
 *  app (anonymous play) is completely unaffected. */
export function AuthProvider({ children }: { children: React.ReactNode }) {
  if (!CLERK_ENABLED) return <>{children}</>;
  return (
    <ClerkProvider publishableKey={CLERK_PUBLISHABLE_KEY} afterSignOutUrl="/">
      {children}
    </ClerkProvider>
  );
}
