# Security Policy

Hazzel runs commands and edits files on your machine, so security matters. Thanks for helping keep it safe.

## Reporting a vulnerability

**Please don't open a public issue for security problems.**

**Email mukundzha33@gmail.com directly** — that's the fastest way to reach me, and security reports always jump the queue. If you'd rather not use email, go to the [Security tab](https://github.com/mukundzha/hazzel/security) and click **Report a vulnerability**.

Please include:

- What the issue is and how to reproduce it
- The impact (what an attacker could do)
- Your OS, Python version, and Hazzel version

You'll get a reply as soon as possible, and we'll keep you updated until it's fixed. Reporters are credited in the changelog unless they prefer to stay anonymous.

## What counts

Anything that breaks Hazzel's safety promises, for example:

- Edits, shell commands, or git actions running **without user approval**
- Commands escaping the **project root** sandbox
- Blocked git actions (`--force`, `reset --hard`) getting through
- API keys being leaked, logged, or stored with weak permissions

## Supported versions

Hazzel is early-stage. Only the **latest release** on [PyPI](https://pypi.org/project/hazzel/) receives security fixes.

## A note on keys

Hazzel stores keys in `~/.config/hazzel/config.json` with `0600` permissions. Never paste your API keys into issues, PRs, or logs.
