import { proxyToBackend } from "../proxy";

export async function POST(request: Request): Promise<Response> {
  return proxyToBackend("/evaluate", "POST", request);
}
