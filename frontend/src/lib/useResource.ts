"use client";

import { useCallback, useEffect, useState } from "react";
import { errorMessage, isAbort } from "./api/client";

export type Resource<T> =
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | { phase: "ready"; data: T };

/** Reloads when `key` changes (null skips) and aborts stale requests. */
export function useResource<T>(
  key: string | null,
  load: (signal: AbortSignal) => Promise<T>,
): { state: Resource<T>; reload: () => void } {
  const [state, setState] = useState<Resource<T>>({ phase: "loading" });
  const [version, setVersion] = useState(0);

  useEffect(() => {
    if (key === null) return;
    const controller = new AbortController();
    // eslint-disable-next-line react-hooks/set-state-in-effect -- the loading state must show before the request starts
    setState({ phase: "loading" });
    load(controller.signal)
      .then((data) => setState({ phase: "ready", data }))
      .catch((error: unknown) => {
        if (isAbort(error)) return;
        setState({ phase: "error", message: errorMessage(error) });
      });
    return () => controller.abort();
    // `load` is intentionally keyed by `key` so callers can pass an inline function
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, version]);

  const reload = useCallback(() => setVersion((v) => v + 1), []);
  return { state, reload };
}
