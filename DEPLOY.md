# Run the agent 24/7 on Oracle Cloud (free)

On your Mac the agent stops whenever the laptop sleeps, so reminders and morning news can be late or missed.
An Oracle Cloud "Always Free" server keeps it running all the time at no cost.

## 1. Create the server (about 20 minutes, one time)

1. Sign up at oracle.com/cloud/free. Home region: **US Midwest (Chicago)**. A card is needed for verification only.
2. Compute > Instances > Create instance. Name `pesagent`.
3. Image: **Ubuntu 24.04**. Shape: **Ampere VM.Standard.A1.Flex**, 1 OCPU, 6 GB RAM (must say "Always Free").
   If it says "out of capacity", use **VM.Standard.E2.1.Micro** instead (enough without voice notes; set `WHISPER_MODEL=tiny`).
4. SSH keys: "Generate a key pair for me" and **download the private key**. Keep it safe.
5. Create, wait for "Running", copy the **Public IP**.

## 2. Copy the agent up (from your Mac's Terminal)

```
chmod 400 ~/Downloads/ssh-key-*.key
cd ~
scp -i ~/Downloads/ssh-key-*.key -r my-agent/core my-agent/platforms my-agent/*.py my-agent/requirements.txt my-agent/setup_server.sh my-agent/.env ubuntu@YOUR_IP:~/my-agent/
scp -i ~/Downloads/ssh-key-*.key -r my-agent/data ubuntu@YOUR_IP:~/my-agent/
```

(The second line copies your users, memory and reminders. Skip it to start fresh.)

## 3. Start it

**Stop the agent on your Mac first** (Ctrl + C). Two copies with the same bot token fight over messages.

```
ssh -i ~/Downloads/ssh-key-*.key ubuntu@YOUR_IP
cd ~/my-agent && bash setup_server.sh
```

When it shows `active (running)`, message the bot on Telegram.

## Managing it

```
sudo systemctl status pesagent     # running?
sudo journalctl -u pesagent -f     # live logs
sudo systemctl restart pesagent    # after changing .env or code
```

Update the code later: `git pull` on the server (or scp the changed files), then restart.
Downloads breaking: `./venv/bin/pip install -U yt-dlp && sudo systemctl restart pesagent`.

Notes: Instagram and YouTube sometimes block datacenter servers more than home internet. If downloads or
transcripts fail on the server but work on your Mac, add a `cookies.txt` (see README).
