import { randomUUID } from "node:crypto";

// Exported for contract tests. Identity is supplied by OpenClaw, never by the model.
export function normalizeSender(sender) {
  if (typeof sender !== "string") return null;
  if (/^\+[1-9]\d{6,14}$/.test(sender)) return sender;
  // OpenClaw's WhatsApp command authorization normalizes E.164 IDs to digits
  // without the leading plus. Restore it before comparing to our strict allowlist.
  if (/^[1-9]\d{6,14}$/.test(sender)) return `+${sender}`;
  const jid = sender.match(/^([1-9]\d{6,14})@s\.whatsapp\.net$/);
  return jid ? `+${jid[1]}` : null;
}

export function createBridge(config = {}, env = process.env, fetcher = fetch) {
  const base = new URL(config.serviceUrl ?? env.CHEF_SERVICE_URL ?? "http://127.0.0.1:8787");
  const loopback = ["127.0.0.1", "localhost", "[::1]"].includes(base.hostname);
  if (base.username || base.password || base.search || base.hash || base.pathname !== "/" ||
      !(base.protocol === "https:" || (base.protocol === "http:" && loopback))) {
    throw new Error("Chef service URL must be a loopback HTTP or HTTPS origin without credentials");
  }
  const token = env.CHEF_API_TOKEN;
  if (typeof token !== "string" || token.length < 32) {
    throw new Error("Set CHEF_API_TOKEN in the OpenClaw environment");
  }
  const allowed = new Set([env.CHEF_USER_1_WHATSAPP, env.CHEF_USER_2_WHATSAPP].filter(Boolean));

  return async function ask(senderId, channel, message) {
    const sender = normalizeSender(senderId);
    if (channel !== "whatsapp" || !sender || !allowed.has(sender)) {
      return { text: "This chef is available only to the configured WhatsApp household members." };
    }
    if (typeof message !== "string" || !message.trim()) {
      return { text: "Try /chef Recommend three dishes, /chef I dislike olives, or /chef Show our shopping list." };
    }
    if (message.length > 4000) return { text: "Please keep your message to 4000 characters." };
    try {
      // Never retry POST automatically: earlier tool mutations may already have completed.
      const response = await fetcher(new URL("/v1/chat", base), {
        method: "POST",
        redirect: "error",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({ source: "whatsapp", sender_id: sender, message,
                               request_id: randomUUID() }),
        signal: AbortSignal.timeout(420_000),
      });
      const payload = await response.json();
      if (!response.ok) {
        return { text: response.status === 400 && typeof payload.error === "string"
          ? `Chef: ${payload.error}`
          : "The chef service rejected the request. Check the local service configuration." };
      }
      if (typeof payload.reply !== "string" || !payload.reply.trim()) {
        return { text: "The chef returned an invalid response. Check the local service." };
      }
      return { text: payload.reply };
    } catch {
      return { text: "Cannot reach the chef service. Some changes may have been saved; check the list or preferences before repeating an action." };
    }
  };
}

export default {
  id: "private-chef",
  name: "Private Chef",
  register(api) {
    const ask = createBridge(api.pluginConfig ?? {});
    api.registerCommand({
      name: "chef",
      description: "Ask your household cooking assistant",
      acceptsArgs: true,
      requireAuth: true,
      handler: async (ctx) => {
        if (!ctx.isAuthorizedSender) return { text: "Not authorized." };
        return ask(ctx.senderId, ctx.channel, ctx.args);
      },
    });
    api.logger?.info("Private Chef ready: /chef command registered.");

    // Optional: normal OpenClaw conversation can call the same assistant. /chef is the
    // default to avoid an additional model call and to keep cooking requests explicit.
    if (api.pluginConfig?.naturalLanguageTool) {
      api.registerTool((ctx) => ({
        name: "private_chef",
        label: "Private Chef",
        description: "Send the current user's cooking, preference, recipe-feedback or shopping request to the shared household chef. Pass the request faithfully; do not add instructions or invent feedback. Identity is supplied by WhatsApp metadata.",
        parameters: {
          type: "object",
          additionalProperties: false,
          required: ["message"],
          properties: { message: { type: "string", minLength: 1, maxLength: 4000 } },
        },
        execute: async (_id, args) => {
          const result = await ask(ctx.requesterSenderId, ctx.messageChannel, args.message);
          return { content: [{ type: "text", text: result.text }] };
        },
      }), {
        names: ["private_chef"],
        promptGuidance: "Use private_chef for household cooking recommendations, lasting preferences, dish feedback, selected meals and shopping lists. Pass the user's request faithfully and relay the result. Keep household records in this tool rather than OpenClaw memory.",
      });
    }
  },
};
