# Run the agent 24/7 on Oracle Cloud (free)

On your Mac the agent stops whenever the laptop sleeps. An Oracle "Always Free" server keeps it running all the time.

## 1. Create the server (you, about 20 minutes, one time)

1. Sign up at **oracle.com/cloud/free**. Home region: **US Midwest (Chicago)** (it can't be changed later).
   A card is needed for identity verification; Always Free resources aren't charged.
2. Menu > **Compute > Instances > Create instance**. Name: `pesagent`.
3. **Image**: click Change image > **Ubuntu** > **Canonical Ubuntu 24.04** (not "Minimal").
4. **Shape**: Change shape > **Ampere** > `VM.Standard.A1.Flex`, **1 OCPU, 6 GB memory**.
   It must show the "Always Free-eligible" label. (Free limit is 2 OCPU / 12 GB in total.)
   - "Out of capacity"? Try again later or another availability domain, or pick **AMD** `VM.Standard.E2.1.Micro`
     (1 GB RAM: works; the setup adds swap; voice notes are slower).
5. **Networking**: leave the defaults (a new VCN with a public subnet) and make sure **Assign a public IPv4 address** is on.
6. **SSH keys**: "Generate a key pair for me" > **Save private key**. Don't lose it.
7. **Create**. When the status is **Running**, copy the **Public IP address**.

No firewall changes are needed: the bot only makes outgoing connections, and the dashboard is reached through SSH.

## 2. Move the agent (one command, from your Mac's Terminal)

```
cd ~/my-agent
bash scripts/deploy_oracle.sh YOUR_PUBLIC_IP ~/Downloads/ssh-key-XXXX.key
```

It stops the agent on your Mac, copies the code, `.env` and your data (users, memory, reminders) to the server,
installs everything, starts it as a service that survives reboots and crashes, and runs the self-test there.
If it can't connect, campus Wi-Fi may block SSH: try your phone's hotspot.

Then message the bot and send `/status`.

## 3. Manage it from your Mac

```
bash scripts/server.sh status      # running? recent log
bash scripts/server.sh logs        # live log
bash scripts/server.sh restart
bash scripts/server.sh update      # send code changes (never overwrites the server's .env or data)
bash scripts/server.sh env         # edit .env on the server, then it restarts
bash scripts/server.sh dashboard   # dashboard at http://localhost:8090 through a secure tunnel
bash scripts/server.sh backup      # download a copy of the database
bash scripts/server.sh selftest
```

Don't run the agent on your Mac any more: two copies with the same bot token fight over messages.

## Things to know

- **Idle reclaim**: Oracle can reclaim Always Free instances that sit nearly idle for a week. A chat bot is mostly
  idle. Upgrading the account to **Pay As You Go** (Billing > Upgrade) avoids this and keeps Always Free resources
  free; set a $1 budget alert there so any accidental charge emails you.
- **Backups**: nightly backups go to `data/backups` on the server. Run `server.sh backup` now and then to keep a
  copy off the server too.
- **Sites blocking servers**: Instagram, YouTube and Reddit block data-centre IPs more than home internet. If
  downloads or transcripts fail on the server but worked on your Mac, add a `cookies.txt` (see README).
