# Security Policy

## Reporting a vulnerability

If you discover a security vulnerability in ebase, please report it privately rather than opening a public issue.

**Email:** [hello@basetobase.jobs](mailto:hello@basetobase.jobs)

Include:

- A description of the vulnerability
- Steps to reproduce
- The version of ebase you're using
- Any relevant logs or screenshots (redact credentials)

We will acknowledge your report within 48 hours and aim to provide a fix or mitigation within 7 days for critical issues.

## Scope

ebase drives a real Chrome session with your LinkedIn credentials. Security issues we care about include:

- Credential leakage (LinkedIn session tokens, API keys, personal data)
- MCP server vulnerabilities (command injection, unauthorized tool access)
- Data exfiltration from prospect/conversation state files
- Installer or update mechanisms that could execute untrusted code

## Supported versions

| Version | Supported |
| ------- | --------- |
| 1.x     | Yes       |
| < 1.0   | No        |
