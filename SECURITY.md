# Security Policy

## Supported Versions

We provide security updates for the following versions:

| Version | Supported          |
| ------- | ------------------ |
| latest  | :white_check_mark: |
| < latest| :x:                |

As Genji Shimada is a custom bot deployment, we only support the latest version currently running in production. We do not maintain multiple versions or provide backports.

## Reporting a Vulnerability

We take security vulnerabilities seriously and appreciate your efforts to responsibly disclose any issues you find.

### How to Report

**Please do NOT report security vulnerabilities through public GitHub issues.**

Instead, report them privately using one of these methods:

1. **Preferred:** Use GitHub's private vulnerability reporting
   - Go to the [Security tab](https://github.com/tylovejoy/genjishimada/security)
   - Click "Report a vulnerability"
   - Fill out the security advisory form

2. **Alternative:** Email directly
   - Send details to: tylovejoy1@gmail.com
   - Include "SECURITY" in the subject line
   - Provide as much detail as possible (see below)

### What to Include

When reporting a vulnerability, please include:

- **Type of vulnerability** (e.g., SQL injection, XSS, authentication bypass)
- **Location** (file path, URL, or component affected)
- **Step-by-step reproduction** (how to trigger the vulnerability)
- **Proof of concept** (if possible, without causing harm)
- **Potential impact** (what an attacker could achieve)
- **Suggested fix** (if you have ideas, but not required)

### What to Expect

After you submit a vulnerability report:

1. **Acknowledgment:** We aim to acknowledge receipt within **48 hours**
2. **Investigation:** We'll investigate and assess the severity
3. **Status updates:** We'll keep you informed of our progress
4. **Fix development:** We'll develop and test a fix
5. **Deployment:** We'll deploy the fix to production
6. **Disclosure:** We'll coordinate public disclosure with you
7. **Credit:** We'll credit you in the security advisory (if desired)

### Disclosure Policy

- Please allow us reasonable time to fix the vulnerability before public disclosure
- We aim to fix critical vulnerabilities within 7 days, high severity within 14 days
- We'll coordinate the disclosure timeline with you
- We appreciate your patience and responsible disclosure

## Security Best Practices for Contributors

If you're contributing to Genji Shimada, please follow these security guidelines:

### Secrets and Credentials

- **Never commit sensitive data** to the repository
  - No API keys, tokens, passwords, or credentials
  - No `.env` files with real values
  - No private keys or certificates
- **Use environment variables** for all secrets (see `.env.local.example`)
- **Review `.gitignore`** before committing to ensure sensitive files are excluded
- **Check your commits** using `git diff` before pushing

### Database Security

- **Use parameterized queries** - Never concatenate user input into SQL
- **Validate input** - Check types, ranges, and formats before database operations
- **Use connection pooling** - Don't create raw database connections
- **Follow least privilege** - Database users should have minimal required permissions

### API Security

- **Validate all input** - Never trust user-provided data
- **Use authentication** - Protect endpoints with proper auth middleware
- **Rate limiting** - Be aware of rate limits for external APIs
- **HTTPS only** - Never send credentials over HTTP

### Dependencies

- **Keep dependencies updated** - Run `uv sync` regularly
- **Review dependency changes** - Check changelogs for security fixes
- **Report vulnerable dependencies** - Use `pip-audit` or similar tools

### Common Vulnerabilities to Avoid

The following vulnerabilities are common in web applications. Please be mindful when contributing:

- **SQL Injection** - Use parameterized queries, never string concatenation
- **Command Injection** - Validate and sanitize inputs to shell commands
- **Path Traversal** - Validate file paths, avoid user-controlled paths
- **XSS** (Discord embeds) - Sanitize user input in embeds and messages
- **Authentication Bypass** - Test auth logic thoroughly
- **Insecure Deserialization** - Use msgspec safely, validate untrusted data

## Scope

### In Scope

- API endpoints and authentication
- Discord bot commands and event handlers
- Database queries and migrations
- RabbitMQ message handling
- File uploads and storage (MinIO/S3)

### Out of Scope

- Third-party services (Discord API, PostgreSQL, RabbitMQ, etc.)
- Denial of Service (DoS) attacks
- Social engineering attacks against users
- Physical security of servers

## Security Features

Genji Shimada includes several security features:

- **Authentication middleware** - API key and session-based auth
- **Rate limiting** - Built into Litestar framework
- **Input validation** - msgspec struct validation for all data
- **Parameterized queries** - AsyncPG with proper parameter binding
- **Error handling** - No sensitive data in error messages
- **Logging** - Security events logged to Sentry

## Questions

If you have questions about this security policy, please email tylovejoy1@gmail.com.

---

Thank you for helping keep Genji Shimada and the Genji Parkour community safe!
