# Security policy

Lumina is an experimental personal project and **has not undergone an independent security audit**. It should not be assumed production-ready.

## Reporting

Please avoid publicly posting exploits, secrets, local network information, private files, or sensitive logs. If you discover a potential security vulnerability, use GitHub's **Report a vulnerability** / private vulnerability reporting feature when enabled on this repository. If that feature is not available, contact the maintainer privately through their GitHub profile before disclosing technical details.

## Deployment precautions

- Keep development APIs bound to loopback and do not expose them directly to the public internet.
- Treat optional LAN gateways and local certificate authorities as host-specific configuration, not portable defaults.
- Never commit tokens, private keys, authentication databases, personal files, model caches, or user data.
- Review every AI-generated patch and test its actual behavior. Model review alone is not proof of safety.
- Use least privilege for service accounts, filesystem mounts, and network access.

Supported versions and disclosure timelines have not yet been formally established.
