"use client";

import { useEffect, useState } from "react";

/**
 * SSR-safe media query hook.
 *
 * Returns `false` on the server and on the first client render (so the markup
 * matches and hydration does not complain), then the real value once mounted.
 */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(false);

  useEffect(() => {
    const mql = window.matchMedia(query);
    const update = () => setMatches(mql.matches);
    update();
    mql.addEventListener("change", update);
    return () => mql.removeEventListener("change", update);
  }, [query]);

  return matches;
}

/** Phone / small-tablet layout breakpoint — the single column with bottom tabs. */
export function useIsMobile(): boolean {
  return useMediaQuery("(max-width: 1023px)");
}
