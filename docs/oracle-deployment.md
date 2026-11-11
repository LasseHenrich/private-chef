# Oracle Cloud VM deployment

This guide records the deployment of Private Chef to an Oracle Cloud VM. Both
household members use WhatsApp; the VM runs the cooking service and OpenClaw
continuously. The owner's existing WhatsApp account remains the linked account.

The deployed configuration was tested from both phones and continued working
after a VM reboot. Backup setup is documented below; check the timer and its logs
to confirm it has also been installed on your VM.

## Deployment layout

- Ubuntu 24.04 LTS on ARM64 (`aarch64`), with Python 3.12.3.
- Checkout at `/home/ubuntu/private-chef`, running as the `ubuntu` user.
- Project-local Node 24 and OpenClaw under `data/runtime/`.
- OpenClaw version verified during installation: `2026.11.3 (847611d)`.
- Cooking API on `127.0.0.1:8787`; the gateway also binds to loopback.
- Outbound connections to WhatsApp and OpenAI. No public application endpoint,
  domain, reverse proxy, or HTTPS certificate is required for this setup.
- Two systemd services restart the processes and launch them after reboot.

Commands marked **local computer** run on the original development machine.
Commands marked **VM** run inside an SSH session. Replace `YOUR_VM_IP` and
`~/Downloads/your-oracle-key.key` with your VM address and downloaded SSH key.
Real addresses, phone numbers, credentials, and session files are intentionally
omitted from this public document.

## 1. Create the Oracle network and VM

In the Oracle Cloud console, select the account's home region. Use an
Always Free eligible Ampere A1 shape and allocation within the account's current
free limits; check the console's pricing before creating resources.

Under **Networking → Virtual Cloud Networks → Start VCN Wizard**, choose
**Create VCN with Internet Connectivity**:

| Setting | Value |
| --- | --- |
| VCN name | `private-chef-vcn` |
| Compartment | Same as the VM |
| VCN IPv4 CIDR | `10.0.0.0/16` |
| Public subnet IPv4 CIDR | `10.0.0.0/24` |
| Private subnet IPv4 CIDR, if requested | `10.0.1.0/24` |

Leave IPv6 disabled. Review and create the network. The wizard creates the
internet gateway and route rules; the public subnet must have a route for
`0.0.0.0/0` to the internet gateway.

Under **Compute → Instances → Create instance**:

1. Name the VM `private-chef` and select Ubuntu 24.04 for ARM64.
2. Select the Always Free eligible A1 shape and appropriate allocation.
3. Use the default boot-volume performance and an eligible boot-volume size
   (50 GB was suggested during setup).
4. Select `private-chef-vcn` and its **public subnet**.
5. Enable assignment of an ephemeral public IPv4 address to the primary VNIC.
6. Generate and download an SSH key pair, or supply an existing public key.

The public IP belongs to the instance's network interface, not the subnet.
Keep the private key outside the repository.

In the public subnet's security list, allow ingress TCP destination port **22**
from your home connection's public IPv4 address with a `/32` suffix. Leave the
source port range as All. If your home IP changes, update this rule before
connecting again. Do not open port 8787 or the OpenClaw gateway port publicly.

## 2. Connect and install

**Local computer:**

```bash
chmod 600 ~/Downloads/your-oracle-key.key
ssh -i ~/Downloads/your-oracle-key.key ubuntu@YOUR_VM_IP
```

On the first connection, check the host identity before accepting its SSH host
key. **VM:** confirm the OS, architecture, and Python version:

```bash
cat /etc/os-release
uname -m
python3 --version
```

Install the prerequisites and checkout:

```bash
sudo apt update
sudo apt install -y git curl ca-certificates nodejs npm build-essential python3-venv
git clone https://github.com/LasseHenrich/private-chef.git ~/private-chef
cd ~/private-chef
bash scripts/install-openclaw.sh
```

The installer uses system npm to bootstrap a project-local Node 24 runtime, then
installs OpenClaw. Native packages are installed on the ARM VM rather than copied
from the development machine. The installer currently selects `openclaw@latest`,
so a future installation may produce a different version.

Verify the installed version directly:

```bash
PATH="$PWD/data/runtime/node_modules/.bin:$PATH" ./data/runtime/node_modules/.bin/openclaw --version
```

Do not use `python3 run.py openclaw --version`: the wrapper currently rejects
that leading flag and also requires a generated gateway configuration.

## 3. Migrate settings and cooking data

These commands assume the default database path, `data/chef.sqlite3`. Adjust them
if `CHEF_DB_PATH` in `.env` points elsewhere, including in the backup script below.

**VM:** prepare the destination:

```bash
cd ~/private-chef
mkdir -p data
chmod 700 data
```

**Local computer:** stop both the original chef service and OpenClaw gateway with
Ctrl+C. Keep them stopped after migration to avoid two running gateways or
diverging household databases. From your local repository, create a SQLite
snapshot using the backup API:

```bash
cd /path/to/private-chef
python3 - <<'PY'
import os
import sqlite3

os.umask(0o077)
with sqlite3.connect("data/chef.sqlite3") as source:
    with sqlite3.connect("data/chef-transfer.sqlite3") as target:
        source.backup(target)
print("Database snapshot ready.")
PY

scp -i ~/Downloads/your-oracle-key.key \
  .env ubuntu@YOUR_VM_IP:~/private-chef/.env
scp -i ~/Downloads/your-oracle-key.key \
  data/chef-transfer.sqlite3 \
  ubuntu@YOUR_VM_IP:~/private-chef/data/chef.sqlite3
```

Use these transfer commands for a new, stopped destination installation. Before
overwriting an existing deployed database, stop its service and back up its data.
Do not copy only a live SQLite database file while WAL files may be active.

Transfer `.env` privately over SSH. It should contain your API key, API token,
model, household names, and both E.164 WhatsApp numbers. Keep
`CHEF_HOST=127.0.0.1` and the default local service URL.

**VM:** initialize the transferred database and create a fresh gateway config:

```bash
cd ~/private-chef
chmod 600 .env data/chef.sqlite3
python3 run.py setup
python3 run.py configure-openclaw --self-chat
python3 run.py openclaw plugins install @openclaw/whatsapp
python3 run.py openclaw config validate
```

`setup` preserves existing settings and records. Configuration generation creates
`data/openclaw/openclaw.json`, including both configured numbers in the WhatsApp
allowlist. It refuses to overwrite an existing gateway configuration.

Rebuild the runtime and pair WhatsApp afresh on the VM. Do not transplant the
development machine's entire `data/openclaw` directory: its configuration contains
machine-specific paths, and its runtime databases have separate ownership/state.

## 4. Pair WhatsApp and test manually

**VM:**

```bash
cd ~/private-chef
python3 run.py openclaw channels login --channel whatsapp
```

On the account owner's phone, open **WhatsApp → Settings → Linked devices → Link
a device**, then scan the terminal QR code. Treat the QR code and session files
as credentials; do not publish them.

Start the application in the first SSH session:

```bash
python3 run.py serve
```

Open a second SSH session and start the gateway:

```bash
cd ~/private-chef
python3 run.py openclaw gateway
```

Wait for `Private Chef ready: /chef command registered.` and
`Listening for WhatsApp inbound messages`. Test both phones:

- The account owner sends `/chef Recommend three dishes` in WhatsApp's built-in
  **Message yourself** chat. A group containing only yourself is still a group
  and is blocked by this configuration.
- The second household member sends `/chef` in a direct chat with the account
  owner's WhatsApp number.

Bare `/chef` returns help without a model call. A recommendation additionally
tests the cooking service and OpenAI API. Both members share the same database.
Also send an ordinary message such as `Hello` from the second phone and verify
that the bot stays silent. The adapter's default `before_dispatch` hook prevents
ordinary WhatsApp messages from reaching the general agent. Keep
`plugins.entries.private-chef.config.naturalLanguageTool` set to `false`.

## 5. Enable automatic startup

Stop the two manually started processes with Ctrl+C before starting systemd
services. **VM:** create the application service:

```bash
sudo tee /etc/systemd/system/private-chef.service >/dev/null <<'EOF'
[Unit]
Description=Private Chef application
Wants=network-online.target
After=network-online.target
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/private-chef
ExecStart=/usr/bin/python3 -u run.py serve
Environment=PYTHONUNBUFFERED=1
UMask=0077
Restart=always
RestartSec=10
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
EOF
```

Create the gateway service:

```bash
sudo tee /etc/systemd/system/private-chef-whatsapp.service >/dev/null <<'EOF'
[Unit]
Description=Private Chef WhatsApp gateway
Wants=network-online.target private-chef.service
After=network-online.target private-chef.service
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/private-chef
ExecStart=/usr/bin/python3 -u run.py openclaw gateway
Environment=PYTHONUNBUFFERED=1
UMask=0077
Restart=always
RestartSec=10
TimeoutStopSec=360
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now private-chef.service private-chef-whatsapp.service
systemctl is-active private-chef.service private-chef-whatsapp.service
```

Both should report `active`. The application and wrapper read `.env` themselves;
no credentials or systemd `EnvironmentFile` are needed in the unit definitions.

Give the gateway about a minute to connect and test WhatsApp again. Then reboot:

```bash
sudo reboot
```

SSH disconnects. Wait a few minutes and test WhatsApp without opening a new SSH
session. This reboot test succeeded during the original deployment.

## 6. Set up daily backups

**VM:** create the following script. It takes a consistent database snapshot,
retains the latest 14 snapshots, and copies the current `.env`. It does not back
up WhatsApp sessions; those can be recreated by pairing again.

```bash
mkdir -p ~/private-chef/scripts
cat > ~/private-chef/scripts/backup.py <<'PY'
import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

os.umask(0o077)
root = Path("/home/ubuntu/private-chef")
backups = root / "data/backups"
backups.mkdir(mode=0o700, parents=True, exist_ok=True)
stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
destination = backups / f"chef-{stamp}.sqlite3"

with sqlite3.connect((root / "data/chef.sqlite3").as_uri() + "?mode=ro", uri=True) as source:
    with sqlite3.connect(destination) as target:
        source.backup(target)

shutil.copyfile(root / ".env", backups / ".env")

for old in sorted(backups.glob("chef-*.sqlite3"))[:-14]:
    old.unlink()

print(f"Backup created: {destination.name}")
PY

sudo tee /etc/systemd/system/private-chef-backup.service >/dev/null <<'EOF'
[Unit]
Description=Back up Private Chef

[Service]
Type=oneshot
User=ubuntu
UMask=0077
ExecStart=/usr/bin/python3 /home/ubuntu/private-chef/scripts/backup.py
EOF

sudo tee /etc/systemd/system/private-chef-backup.timer >/dev/null <<'EOF'
[Unit]
Description=Daily Private Chef backup

[Timer]
OnCalendar=*-*-* 04:00:00 UTC
Persistent=true

[Install]
WantedBy=timers.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now private-chef-backup.timer
sudo systemctl start private-chef-backup.service
sudo journalctl -u private-chef-backup.service -n 10 --no-pager
systemctl list-timers private-chef-backup.timer
```

Check for `Backup created` and a scheduled next run. The timer runs at 04:00 UTC;
`Persistent=true` catches up a missed scheduled run after downtime.

Snapshots on the VM do not protect against loss of that VM. Periodically copy
them off the server. **Local computer:**

```bash
mkdir -p ~/private-chef-backups
chmod 700 ~/private-chef-backups
scp -r -i ~/Downloads/your-oracle-key.key \
  ubuntu@YOUR_VM_IP:~/private-chef/data/backups/. \
  ~/private-chef-backups/
```

This off-server copy is manual; automatic off-server backup is not configured by
this guide. The directory contains API credentials and household data. Keep it
private and outside Git. Local downloaded copies are not pruned by the VM's
retention policy. The generated `scripts/backup.py` is a VM-local helper; it is
not created in a fresh checkout until you run the commands above.

## Maintenance and troubleshooting

Run administrative commands **on the VM** from `~/private-chef`.

Check processes and recent logs:

```bash
systemctl is-active private-chef.service private-chef-whatsapp.service
sudo journalctl -u private-chef.service -u private-chef-whatsapp.service -n 60 --no-pager
```

Review logs privately before sharing excerpts: gateway logs may contain phone
numbers, message contents, QR codes, or session information.

After editing `.env`, restart both services:

```bash
sudo systemctl restart private-chef.service private-chef-whatsapp.service
```

When changing a household phone number, also update
`channels.whatsapp.allowFrom` in `data/openclaw/openclaw.json` before restarting.
Keep `selfChatMode: true`, `dmPolicy: "allowlist"`, and groups disabled for this
deployment. See [the OpenClaw guide](openclaw.md) for the routing details.

If WhatsApp needs pairing again, stop its gateway first:

```bash
sudo systemctl stop private-chef-whatsapp.service
python3 run.py openclaw channels login --channel whatsapp
sudo systemctl start private-chef-whatsapp.service
```

For application updates, create and verify a backup, review local changes with
`git status`, and stop both services before pulling a reviewed revision. Use
`git pull --ff-only` so divergent histories are not merged implicitly. Then run
`python3 run.py setup` and restart both services. Do not rerun the OpenClaw
installer as a routine application update: it selects the latest runtime and
may introduce a separate compatibility change.

After fixing a repeated startup failure, clear systemd's restart limit if needed:

```bash
sudo systemctl reset-failed private-chef.service private-chef-whatsapp.service
sudo systemctl restart private-chef.service private-chef-whatsapp.service
```

To restore household data, stop both services, preserve the current database and
any `-wal`/`-shm` files together in a separate private directory, then place the
chosen snapshot at `data/chef.sqlite3`. Do not leave old WAL/SHM files beside the
restored database. Set database permissions to `600`, run `python3 run.py setup`,
and restart both services. On a replacement VM, restore `.env` privately and
follow the fresh configuration and WhatsApp pairing steps rather than copying
old gateway runtime state.

The current Python HTTP server remains a local development server. This deployment
keeps it behind loopback for this small household setup; it does not make it a
public production API. Review [architecture notes](architecture.md) before
expanding access or introducing additional workers.
