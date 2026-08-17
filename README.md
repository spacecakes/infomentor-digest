# infomentor-digest

Reads InfoMentor for every child on your account and sends what changed to a
Telegram chat, to e-mail, or to both.

The official app (well, web wrapper) is slow, cumbersome and buggy so I just rarely use it, mostly because it fails to notify me and every time I open myself I am reminded of how much better Tyra was. But I still want to know what's going on, so I made this to distill the info from their endpoints into a more easily accessible format. It uses a Chromium instance to browse their web so we don't have to, then reports back in an easy-to-read format.

Unofficial. No connection to InfoMentor.

## What it reports

Each child gets a block. The sections run in reading order: what needs you, then what happens, then what is only worth knowing. No AI and no paid service. The digest is grouped plain text, and the endpoint a fact came from decides its section.

| Section  | Content                                                                                  |
| -------- | ---------------------------------------------------------------------------------------- |
| Att göra | missing attendance times, an open utvecklingssamtal, meeting times to book, homework due |
| Kalender | events for the next weeks and days the school closes, in one date order                  |
| Nytt     | news posts with their full text, Lärlogg entries with their photos                       |

A section prints only when it has something under it. Attachments like photos and PDFs are downloaded and forwarded.

## Quiet by design

Every fact carries a key, and each channel remembers the keys it reported. A run therefore shows what changed and nothing else.

The first run for a child records its keys and sends nothing — otherwise day one would send every news post of the term. **Expect silence after you start it.** The first digest comes with the first change.

To start over, delete `data/reported.json`. The run after that is as quiet as day one.

## Install

```bash
git clone https://github.com/spacecakes/infomentor-digest.git
cd infomentor-digest
sudo ./setup.sh
```

The script builds a virtual environment, installs Chromium, asks what the digest needs, writes `.env`, sends a test message, and starts a systemd service that keeps reporting. Run it without `sudo` to skip the service and report by hand.

You need Python 3.12 or later, and:

- An InfoMentor **username and password**. The digest cannot answer a BankID prompt, so e-legitimation does not work.
- A Telegram bot, or an SMTP relay that takes mail without a login. Set both and every digest goes to both.

Make the Telegram bot first: write to `@BotFather`, send `/newbot`, and keep the token. Setup asks for the token, waits while you write to your bot, then reads the chat id itself. To reach two parents, put the bot in a group and send `/start` there.

## Running it

```bash
journalctl -u infomentor-digest -f       # watch the service
.venv/bin/infomentor-digest run          # send what's new (if anything)
.venv/bin/infomentor-digest test-notify  # check delivery
```

To update, `git pull` and run `sudo ./setup.sh` again: it installs what the checkout now holds and restarts the service, keeping your `.env`.

### Run modifiers

| Flag        | Effect                                              |
| ----------- | --------------------------------------------------- |
| `--sample`  | send one fact per section and remember none of them |
| `--dry-run` | print the digest instead of sending it              |

`run --sample` is the test send: real facts, one line under each section, and an attachment where the section has one. It remembers nothing, so the facts it showed still arrive in the digest they belong to. Add `--dry-run` to read it on screen and send nothing.

## Settings

`.env` holds them, `env.example` lists every one with its default, and an environment variable wins over the file. Edit `.env`, then `systemctl restart infomentor-digest` to pick it up.

Every channel you set up gets the digest and keeps its own reported keys. A channel that fails is written to the log, the others still deliver, and the facts it missed come back on the next run.

## Troubleshooting

| Symptom                               | Cause                                                                                               |
| ------------------------------------- | --------------------------------------------------------------------------------------------------- |
| `chat not found`                      | Telegram made your group a supergroup and the id changed. Put the new `TELEGRAM_CHAT_ID` in `.env`. |
| Telegram accepts nothing              | Nobody wrote to the bot. A bot cannot open a chat itself.                                           |
| Nothing arrives, and the log is quiet | The run seeded, or nothing changed. `run --sample` proves delivery works.                           |
| The login fails                       | Check the password on infomentor.se. Only a username and password work, not BankID.                 |
| A file never arrives                  | Telegram takes a photo up to 10 MB and a document up to 50 MB.                                      |
| Chromium will not start               | Its system libraries are missing. Run `sudo ./setup.sh` on the machine itself.                      |

## Licence

MIT. See `LICENSE`.
