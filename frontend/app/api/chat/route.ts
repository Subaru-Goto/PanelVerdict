import { proxyPost } from "../proxy";

export async function POST(request: Request): Promise<Response> {
  return proxyPost("/chat", request);
}
