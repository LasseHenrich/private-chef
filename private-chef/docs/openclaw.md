# WhatsApp and OpenClaw

## Connection design

OpenClaw's WhatsApp plugin uses Baileys and a linked WhatsApp Web session, rather
than Meta's official Business API. That avoids a paid messaging provider, but means
the connection is unofficial: account restrictions, QR re-pairing and compatibility
changes remain possible. Use a separate bot account if practical.

`/chef <message>` is registered as a native OpenClaw command. It goes directly to
the local service, which calls OpenAI. It does not need a second OpenClaw agent turn.
The plugin only admits your two configured WhatsApp numbers. The service independently
maps trusted sender metadata to `person-1`/`person-2`; message text cannot choose an
identity. Both chats use the same database. Context is kept per person, so ambiguous
references to the other person's messages may need a recipe ID or title.

## Installation and setup

1. Install a current OpenClaw release using its [official installation guide](https://docs.openclaw.ai/install).
   Use the Node.js version required by that release. The development environment used
   for this implementation had Node 20 and no installed OpenClaw; live compatibility
   must be checked during setup.
2. Run `python3 run.py setup` if you have not already, and populate `.env` with your
   OpenAI key, names and both E.164 numbers:

   ```dotenv
   CHEF_USER_1_WHATSAPP=+491234567890
   CHEF_USER_2_WHATSAPP=+499876543210
   ```

3. Generate an isolated gateway configuration:

   ```bash
   python3 run.py configure-openclaw
   ```

   It writes private configuration under `data/openclaw/`. It does not alter your
   global OpenClaw configuration. It refuses to overwrite an existing file. After
   changing numbers, update `allowFrom` there and restart both processes; `.env` is
   also enforced by the plugin and the service.

4. Run OpenClaw through the wrapper so `.env` and the isolated state path are supplied
   without exposing keys as command-line arguments:

   ```bash
   python3 run.py openclaw plugins install @openclaw/whatsapp
   python3 run.py openclaw config validate
   python3 run.py openclaw plugins list
   python3 run.py openclaw channels login --channel whatsapp
   ```

   The local Private Chef plugin is loaded from the repository path in the generated
   config; no npm install is needed for that plugin. The WhatsApp plugin itself is a
   separate OpenClaw installation. Scan the login QR with the bot's WhatsApp account
   under **Settings → Linked devices**. Treat QR codes and session files as secrets.

5. Start both processes, in separate terminals:

   ```bash
   python3 run.py serve
   ```

   ```bash
   python3 run.py openclaw gateway
   ```

6. From each configured phone, message the bot:

   ```text
   /chef What preferences do you have for me?
   /chef Recommend three dishes for both of us
   ```

If the gateway reports an incompatible configuration or plugin API, stop and resolve
it before enabling broad access. The adapter uses the public `registerCommand`
contract; tests exercise that contract but do not run OpenClaw itself.

## Optional natural-language routing

The explicit `/chef` command is the default. To also let OpenClaw's agent route
ordinary cooking messages, edit `data/openclaw/openclaw.json`:

```json
{
  "plugins": {
    "entries": {
      "private-chef": {
        "enabled": true,
        "config": { "naturalLanguageTool": true }
      }
    }
  },
  "tools": { "profile": "messaging", "alsoAllow": ["private_chef"] }
}
```

Merge those keys into the existing object; do not replace the complete file with
this fragment. Restart the gateway. This mode requires an OpenClaw model configuration
and can incur an extra model call. The tool obtains sender identity from the host's
`requesterSenderId`, never from model arguments. Missing or unrecognized identities
are rejected. The generated configuration already selects your `.env` OpenAI model.

## Optional shared group

Private chats are the configured default. After checking private chats, add the bot
to your dedicated cooking group and update only the WhatsApp block:

```json
{
  "groupPolicy": "allowlist",
  "groupAllowFrom": ["+491234567890", "+499876543210"],
  "groups": { "YOUR_GROUP_ID@g.us": { "requireMention": false } }
}
```

Use the actual group ID shown by OpenClaw and retain `dmPolicy` and `allowFrom`.
Do not use a wildcard group entry unless you want all groups admitted. Continue to
use `/chef` for explicit requests. Replies in a group are visible to everyone in it.

## Troubleshooting

- **Unknown sender:** verify E.164 numbers in `.env` and gateway `allowFrom`. Phone
  JIDs ending `@s.whatsapp.net` are normalized; opaque `@lid` identities fail closed.
  If your OpenClaw version emits those identities, resolve them through trusted
  gateway metadata before changing the adapter; do not infer identity from chat text.
- **Cannot reach chef:** check that `python3 run.py serve` is running. The launcher
  passes `CHEF_API_TOKEN` to the gateway. Restart both after changing it.
- **OpenAI key/model rejected:** update `.env` with a valid API key and an available
  Responses-compatible model, then restart the service.
- **Request times out:** check the shared list/preferences before repeating a mutation.
  The adapter intentionally does not retry a POST automatically.
- **QR or session problems:** use the installed release's `channels` diagnostics.
  Do not paste authentication files or QR screenshots into public GitHub issues.

References: [WhatsApp integration](https://docs.openclaw.ai/channels/whatsapp),
[plugin development](https://docs.openclaw.ai/plugins/building-plugins),
[public command contract](https://github.com/openclaw/openclaw/blob/main/src/plugins/plugin-command.types.ts).
