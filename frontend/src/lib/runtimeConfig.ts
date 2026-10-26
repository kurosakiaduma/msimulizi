export type RuntimeConfig = { backendUrl: string; wsUrl: string };

function getApiBase(): string {
  if (typeof window === "undefined") return "";
  return (
    process.env.NEXT_PUBLIC_BACKEND_URL ??
    `http://${window.location.hostname}:8000`
  ).replace(/\/$/, "");
}

function getWsBase(): string {
  if (typeof window === "undefined") return "";
  return (
    process.env.NEXT_PUBLIC_WS_URL ??
    `${getApiBase().replace(/^http/, "ws")}/ws`
  ).replace(/\/$/, "");
}

/**
 * Read connection URLs from the server at runtime.
 *
 * `NEXT_PUBLIC_*` values are inlined into the bundle at build time, but the
 * container image is built before the backend hostname exists. The
 * `/api/config` route handler reads `BACKEND_URL` and `WS_URL` at request time
 * so the same image works in every environment.
 */
export async function loadRuntimeConfig(): Promise<RuntimeConfig> {
  try {
    const resp = await fetch("/api/config", { cache: "no-store" });
    if (resp.ok) {
      const data = (await resp.json()) as Partial<RuntimeConfig>;
      return {
        backendUrl: data.backendUrl || getApiBase(),
        wsUrl: data.wsUrl || getWsBase(),
      };
    }
  } catch {
    // Fall through to the local-development defaults.
  }

  return { backendUrl: getApiBase(), wsUrl: getWsBase() };
}
