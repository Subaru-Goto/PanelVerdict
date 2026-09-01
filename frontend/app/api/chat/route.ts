import { proxyToBackend } from "../proxy";

export async function POST(request: Request): Promise<Response> {
  return proxyToBackend("/chat", "POST", request);
}
