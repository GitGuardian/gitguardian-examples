# GitGuardian Examples

Practical examples and reference implementations for integrating GitGuardian into developer and security workflows.

This repository contains standalone projects demonstrating how to use GitGuardian APIs, secret detection capabilities, and other GitGuardian tooling in real-world scenarios.

Each example lives in its own directory with setup instructions, requirements, and documentation.

## Examples

### GitGuardian API Remediation Workflow Notebook

A notebook demonstrating how to use the GitGuardian API as part of a secrets remediation workflow.

[View the example](./api-remediation-notebook)

### Secret Scanning in an AI Gateway

An AI gateway in front of OpenAI, Anthropic, and Mistral that scans every prompt and completion with GitGuardian and blocks the call if a secret is found.

[View the example](./ai-gateway-secret-scanning)

### Secret Scanning of GitHub Issues and Pull Requests

A webhook receiver and a backfill command that scan GitHub issues, pull requests, comments, and reviews, and raise the secrets they find as incidents on a GitGuardian custom source.

[View the example](./github-issues-prs-secret-scanning)

## Getting started

Clone the repository and navigate to the example you want to explore:

```bash
git clone https://github.com/GitGuardian/gitguardian-examples.git
cd gitguardian-examples
```

Follow the README in each example directory for installation and usage instructions.

## Questions

For questions or feedback about these examples, contact `devrel@gitguardian.com`.
