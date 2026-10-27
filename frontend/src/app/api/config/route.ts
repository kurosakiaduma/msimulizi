/**
 * Runtime connection settings for the browser.
 *
 * `NEXT_PUBLIC_*` values are inlined at build time, but this app is deployed as
 * a prebuilt container where the backend hostname is only known after
 * provisioning. Reading the environment in a route handler keeps the value
 * dynamic, so one image works across environments.
 */
export const dynamic = "force-dynamic";

export async function GET() {
  const backendUrl = (process.env.BACKEND_URL ?? "").replace(/\/$/, "");
  const wsUrl = (
    process.env.WS_URL ??
    (backendUrl ? `${backendUrl.replace(/^http/, "ws")}/ws` : "")
  ).replace(/\/$/, "");

  return Response.json(
    { backendUrl, wsUrl },
    { headers: { "Cache-Control": "no-store" } }
  );
}
