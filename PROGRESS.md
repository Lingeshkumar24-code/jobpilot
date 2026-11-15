# JobPilot AI — Development Status

Last reviewed: 2026-11-15. This status is based on source inspection and the
tests explicitly listed below. AWS resources and live n8n workflows have not
been deployed or verified.

| Master phase | Status | Evidence / remaining work |
|---|---|---|
| 1. Repository foundation | Partial | App, Dockerfiles, Compose, models and migration exist. No Git metadata is present in this workspace; project history cannot be checked. |
| 2. Frontend dashboard | Partial | Responsive dashboard routes exist; overview uses live API. Review mobile/accessibility and remove unused sample-data fixture. |
| 3. Authentication/profile | Implemented locally | Cookie auth, profile CRUD, user-scoped API. Backend suite passes. Production deployment not verified. |
| 4. Resume management | Implemented locally | PDF/DOCX validation, private local/S3 storage, deterministic parsing with optional grounded LLM refinement, profile update, versions and downloads. AWS S3 path not live-tested. |
| 5. Natural language search | Implemented locally | Rule-based parsing, optional LLM refinement, filter validation, refinement and saved history. OpenRouter integration and the configured local key have been exercised. |
| 6. Job sources | Partial | Public feeds, Greenhouse/Lever connectors, and Firecrawl web search are implemented. Firecrawl results are restricted to identifiable job detail pages; broad board/search pages are discarded. Role filtering checks titles. LinkedIn/Indeed/Naukri official API credentials and source-specific connectors remain; Wellfound/company-page connectors remain. |
| 7. LangGraph agents | Partial | Graph, interrupt, audit and approval pause exist. Checkpoint saver is in-memory, not durable. Not all nine roles are independent agents. |
| 8. Matching | Implemented locally | Explainable weighted deterministic scoring, optional embeddings. pgvector is not enabled. |
| 9. n8n workflows | Partial | Six JSON exports now exist and API supports signed webhooks. Resume workflow is intentionally disabled; no email/push notification, n8n auth hardening, live import or live schedule verification. |
| 10. Browser automation | Partial | Isolated Playwright worker code supports form analysis/fill, screenshots, CAPTCHA/login detection and signed one-time approval. Container entry point now targets the real worker app. Local browser worker was unreachable during the UI session because Docker is unavailable; the current application preview could not be inspected. |
| 11. Approval center | Implemented locally | Preview/edit/reject/approval actions and one-time application-bound proof. |
| 12. Application tracking | Partial | Application states/events/outcomes and evidence-gated confirmation exist. External employer updates require user confirmation; no notification integration. |
| 13. Docker/local integration | Partial | Compose and service Dockerfiles exist. Full compose boot and end-to-end integration have not been verified in this review. |
| 14. AWS manual learning deployment | Pending | No EC2/manual AWS deployment or account verification. |
| 15. Terraform | Partial | VPC/NAT, ALB, ECS, RDS, S3, ECR, IAM/SSM and CloudWatch code exists. Not applied/validated against AWS. EC2, SQS, Lambda, API Gateway, budget and GitHub OIDC role are absent. |
| 16. ECS migration | Partial | Task/service definitions exist; no live deployment. Browser-worker default desired count is zero, but no queue-driven scale-from-zero path is implemented, so application preparation requires manually scaling the ECS worker service. n8n/background agent worker are not separate ECS services. |
| 17. CI/CD | Partial | CI and manual/tag deploy workflows exist. OIDC role and GitHub environment variables/secrets must be configured; pipeline has not run against AWS. |
| 18. Security/performance | Partial | Several application safeguards exist; full security review, vulnerability scan, load/performance checks and deployment hardening remain. |
| 19. Production readiness | Pending | HTTPS certificate, production secrets, durable checkpoints/queue, migration strategy, monitoring, backup/restore rehearsal, cost controls and live deployment verification remain. |
| 20. Documentation/final verification | Partial | Core and AWS guides updated; install/deploy steps still need validation against live environment and remaining architecture. |

## Verification performed in this review

- Backend tests: **9 passed** (includes a regression test for description-text role false positives).
- Browser-worker tests: **11 passed** against the local mock application site.
- Browser worker runtime: not reachable in the local app session because Docker is unavailable; the Dockerfile now starts `app:app`, but an image rebuild or a separately started worker is required.
- OpenRouter integration: implemented, configured locally, and live-tested during resume parsing.
- Firecrawl live search: configured and returned results. The first trial exposed aggregator search pages, which are now filtered. A direct ATS-domain trial returned a mix of job details and career portals; search relevance still needs live tuning.
- Terraform/AWS: not validated against AWS credentials and no resources were created.
- n8n: exports/API were inspected; workflows were not imported or run in a live n8n instance.

## External setup still needed

- Keep `OPENROUTER_API_KEY` and `FIRECRAWL_API_KEY` in the local backend `.env` or a secret manager. Never commit either key or paste it into source control.
- Browser worker dependencies: install `browser-worker/requirements.txt` in
  its own Python environment, including Playwright and Chromium.
- AWS account/IAM/OIDC, GitHub environment settings, domain and TLS certificate
  are needed before deployment. AWS account credentials are not needed for
  local development.
- Authorized API credentials are needed only if enabling gated job sources.
