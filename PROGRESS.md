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

- Backend tests: **12 passed** in 13.03s (`pytest tests/test_api.py -v`):
  - `test_registration_cookie_session_and_csrf` (session cookies, CSRF protection, profile update)
  - `test_firecrawl_builds_role_and_location_query` (structured search query composition)
  - `test_firecrawl_extracts_title_and_company_from_job_results` (title, company, URL validation, aggregator rejection)
  - `test_firecrawl_skips_when_api_key_missing` (graceful skip when unconfigured)
  - `test_resume_upload_parse_and_download` (DOCX parsing, profile update, versioning)
  - `test_search_uses_real_filters_and_explainable_scores` (grounded filters, explainable weights)
  - `test_role_filter_uses_job_title_not_description_text` (prevents keyword-stuffing false positives)
  - `test_application_cannot_submit_without_approval` (one-time approval proof requirement)
  - `test_unknown_submission_is_never_reported_confirmed` (strict evidence requirement)
  - `test_agent_pauses_for_human_approval_then_submits` (LangGraph approval interrupt & signed resume)
  - `test_n8n_webhook_signature_and_idempotency` (HMAC verification and delivery deduplication)
  - `test_system_status_reports_real_configuration` (system health and runtime reporting)
- Browser-worker tests: **11 passed** in 25.91s (`pytest tests/test_worker.py -v` against mock site):
  - `test_health_and_auth` (worker secret header validation)
  - `test_analyze_detects_form_fields` (DOM field extraction, screenshot capture)
  - `test_fill_fields_and_resume` (field population, file attachment, validation checking)
  - `test_submission_requires_valid_one_time_approval` (HMAC approval proof verification)
  - `test_nonce_is_single_use_across_sessions` (replay attack prevention via SQLite nonce journal)
  - `test_captcha_is_detected_and_blocks_submission` (automatic stop on CAPTCHA)
  - `test_login_wall_is_detected` (automatic stop on password/login walls)
  - `test_validation_errors_block_submission` (prevents partial/invalid form submission)
  - `test_unknown_submission_status_is_not_reported_as_confirmed` (refuses to fabricate confirmations)
  - `test_required_unknown_field_is_flagged` (stops when unsupported required inputs are present)
  - `test_ssrf_guard_blocks_private_addresses` (blocks internal IP navigation)
- Live End-to-End Browser Automation (`test_live_e2e_flow.py`): **100% PASSED (15/15 stages verified)**:
  - 1. Started live mock employer application portal on `127.0.0.1:8765/apply`.
  - 2. Initialized database schema and headless Playwright Chromium worker engine.
  - 3. Registered candidate (`Arjun Sharma`, `arjun.sharma@example.com`).
  - 4. Populated candidate profile (4 yrs experience, skills, location).
  - 5. Uploaded and parsed resume DOCX attachment (`Arjun_Sharma_Resume.docx`).
  - 6. Discovered target job opening (`AI Engineer` at `Acme Robotics`) with match score **94.1%** (4/4 matched skills).
  - 7. Created application tracking record (`bff0b36d-a4f8-4b8d-8b2d-7f9ef3ecbb59`).
  - 8. Browser worker opened employer page, extracted DOM fields, generated structured answers, captured initial screenshot (`screenshot_1_form_analyzed.png`).
  - 9. Candidate reviewed answers and explicitly checked required privacy policy consent checkbox.
  - 10. Playwright filled all 8 form inputs (Name, Email, Phone, Country, Cover letter, attached resume binary) and verified zero validation errors (`screenshot_2_form_filled.png`).
  - 11. Tested submission safety guard without approval: blocked with HTTP 409 Conflict.
  - 12. Requested application approval token (issued with 1-hour expiration).
  - 13. Candidate approved application; generated cryptographic HMAC-SHA256 one-time signed proof with unique nonce.
  - 14. Browser worker clicked submit with proof, verified employer receipt, detected employer reference number `F121BB81` on confirmation page (`screenshot_3_submission_confirmed.png`), updated status to `CONFIRMED`.
  - 15. Tested duplicate submission replay with the same proof: blocked with HTTP 409 Conflict.
- Frontend verification:
  - TypeScript type check (`npx tsc --noEmit`): **0 errors**
  - Production build (`npm run build`): **Compiled successfully (15/15 static routes generated)**
- Git repository:
  - Initialized with remote `https://github.com/Lingeshkumar24-code/jobpilot.git` on branch `master`.
- Security & configuration:
  - Fixed `_update_existing` attribute name bug in `app/services/discovery.py`.
  - Fixed `run_agent` node completion status and error propagation in `app/agents/graph.py`.
  - Fixed `_active_session` lookup and browser client routing across sessions in `app/services/applications.py`.
  - Added safe passthrough of `FIRECRAWL_API_KEY` and `OPENROUTER_API_KEY` in `docker-compose.yml` and `infra/terraform`.
  - Documented n8n workflow catalogue and configuration in `n8n/README.md`.
- Deployments & AWS:
  - No AWS resources were created or destroyed.
  - No remote git push performed (requires user's GitHub credentials).

## External setup still needed

- Keep `OPENROUTER_API_KEY` and `FIRECRAWL_API_KEY` in the local backend `.env` or a secret manager. Never commit either key or paste it into source control.
- Browser worker dependencies: install `browser-worker/requirements.txt` in
  its own Python environment, including Playwright and Chromium.
- AWS account/IAM/OIDC, GitHub environment settings, domain and TLS certificate
  are needed before deployment. AWS account credentials are not needed for
  local development.
- Authorized API credentials are needed only if enabling gated job sources.
