import assert from "node:assert/strict";
import test from "node:test";
import plugin, { createBridge, normalizeSender } from "./index.mjs";

const env = { CHEF_API_TOKEN: "test-token-".repeat(4), CHEF_USER_1_WHATSAPP: "+491111111111",
              CHEF_USER_2_WHATSAPP: "+492222222222" };

test("bridge trusts metadata and sends the service token only in headers", async () => {
  let request;
  const ask = createBridge({}, env, async (url, options) => {
    request = { url, options };
    return { ok: true, json: async () => ({ reply: "Here are three dishes" }) };
  });
  const reply = await ask("492222222222@s.whatsapp.net", "whatsapp", "Recommend dinner");
  assert.equal(reply.text, "Here are three dishes");
  assert.equal(request.url.href, "http://127.0.0.1:8787/v1/chat");
  const body = JSON.parse(request.options.body);
  assert.equal(body.sender_id, env.CHEF_USER_2_WHATSAPP);
  assert.equal(body.source, "whatsapp");
  assert.equal(body.member_id, undefined);
  assert.equal(body.token, undefined);
  assert.ok(body.request_id);
  assert.equal(request.options.redirect, "error");
});

test("unknown senders, channels and linked identities fail closed", async () => {
  const ask = createBridge({}, env, async () => assert.fail("must not call service"));
  for (const [sender, channel] of [["+493333333333", "whatsapp"], [env.CHEF_USER_1_WHATSAPP, "web"],
                                  ["123456789@lid", "whatsapp"], [undefined, "whatsapp"]]) {
    assert.match((await ask(sender, channel, "Hi")).text, /configured/);
  }
  assert.equal(normalizeSender("491111111111@s.whatsapp.net"), env.CHEF_USER_1_WHATSAPP);
});

test("service URL and token validation prevent accidental credential leaks", () => {
  for (const serviceUrl of ["http://public.example", "https://user:password@example.com",
                             "https://example.com/path", "https://example.com/?token=x"]) {
    assert.throws(() => createBridge({ serviceUrl }, env));
  }
  assert.throws(() => createBridge({}, {}));
});

test("network failures are sanitized and never retried", async () => {
  let calls = 0;
  const ask = createBridge({}, env, async () => { calls++; throw new Error(env.CHEF_API_TOKEN); });
  const result = await ask(env.CHEF_USER_1_WHATSAPP, "whatsapp", "Add rice");
  assert.match(result.text, /Some changes may have been saved/);
  assert.ok(!result.text.includes(env.CHEF_API_TOKEN));
  assert.equal(calls, 1);
});

test("plugin registers an authenticated command without needing an OpenClaw model", async () => {
  const old = { ...process.env };
  Object.assign(process.env, env);
  try {
    let command;
    plugin.register({ registerCommand: (value) => { command = value; }, pluginConfig: {} });
    assert.equal(command.name, "chef");
    assert.equal(command.requireAuth, true);
    assert.match((await command.handler({ isAuthorizedSender: false })).text, /Not authorized/);
    const help = await command.handler({ isAuthorizedSender: true, channel: "whatsapp",
                                         senderId: env.CHEF_USER_1_WHATSAPP });
    assert.match(help.text, /Try \/chef/);
  } finally {
    for (const key of Object.keys(env)) {
      if (old[key] === undefined) delete process.env[key]; else process.env[key] = old[key];
    }
  }
});

test("optional natural-language tool obtains identity from trusted factory context", async () => {
  const old = { ...process.env };
  Object.assign(process.env, env);
  try {
    let factory;
    plugin.register({ registerCommand: () => {}, registerTool: (value) => { factory = value; },
                      pluginConfig: { naturalLanguageTool: true } });
    const tool = factory({ messageChannel: "whatsapp", requesterSenderId: "+493333333333" });
    assert.deepEqual(Object.keys(tool.parameters.properties), ["message"]);
    assert.match((await tool.execute("c1", { message: "Hi" })).content[0].text, /configured/);
  } finally {
    for (const key of Object.keys(env)) {
      if (old[key] === undefined) delete process.env[key]; else process.env[key] = old[key];
    }
  }
});
