# How the agent talks

Edit these files to change the agent's personality, rules and tone. Changes apply to the next
message, no restart needed.

- `owner.md`: how it talks to you (your profile, goals, thinking frameworks, output style).
- `public.md`: how it talks to everyone else.

Tips: plain sentences work best. Put the most important rules near the top. Keep the
"never use markdown" rule, because Telegram shows asterisks literally.

Other controls (in Telegram):
- `/thinking off|low|medium|high` (owner): how hard the models think before answering.
- `/think <question>` (owner): think hard for one message.
- `/style <how you want replies>` (anyone): personal reply style, e.g. "short, bullet-free, Hinglish".
- `REPLY_MAX_TOKENS` in .env: the longest reply allowed (default 2048, about 1,500 words).
