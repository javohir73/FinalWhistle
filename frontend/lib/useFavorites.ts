"use client";

import { useCallback, useEffect, useState } from "react";

const KEY = "pp:favorites";
const EVENT = "pp:favorites-changed";

function read(): string[] {
  if (typeof window === "undefined") return [];
  try {
    return JSON.parse(window.localStorage.getItem(KEY) ?? "[]");
  } catch {
    return [];
  }
}

/** Favorite teams, persisted in localStorage and synced across components/tabs. */
export function useFavorites() {
  const [favorites, setFavorites] = useState<string[]>([]);

  useEffect(() => {
    setFavorites(read());
    const sync = () => setFavorites(read());
    window.addEventListener(EVENT, sync);
    window.addEventListener("storage", sync);
    return () => {
      window.removeEventListener(EVENT, sync);
      window.removeEventListener("storage", sync);
    };
  }, []);

  const toggle = useCallback((team: string) => {
    const current = read();
    const next = current.includes(team)
      ? current.filter((t) => t !== team)
      : [...current, team];
    window.localStorage.setItem(KEY, JSON.stringify(next));
    window.dispatchEvent(new Event(EVENT));
    setFavorites(next);
  }, []);

  const isFavorite = useCallback(
    (team: string) => favorites.includes(team),
    [favorites],
  );

  return { favorites, toggle, isFavorite };
}
