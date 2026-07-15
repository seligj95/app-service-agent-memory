# Contributing

Contributions are welcome through issues and pull requests.

1. Create a focused branch.
2. Run `uv sync --python 3.13 --all-groups`.
3. Make the smallest complete change.
4. Run the formatting, linting, typing, and test commands documented in the README.
5. Do not include credentials, connection strings, user memory, or model transcripts.

Infrastructure changes should preserve passwordless authentication, least-privilege data-plane
access, and the deployment workflow in `.azure/deployment-plan.md`.
