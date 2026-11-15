# JobPilot AI

AI-powered job discovery and application assistant. Upload a resume, search
jobs in natural language, get AI-matched listings from multiple sources,
and use a supervised browser agent to prepare (never silently submit)
applications — every submission requires your explicit, application-specific
approval.

See **PROGRESS.md** for what's built so far and what's next.
The current browser search workflow and its screenshots are documented in
[`docs/browser-search-workflow.md`](docs/browser-search-workflow.md).

## Stack

- **Frontend:** Next.js, React, TypeScript, Tailwind, shadcn/ui
- **Backend:** Python 3.13, FastAPI, SQLAlchemy, Alembic
- **AI:** LangGraph, OpenRouter free models, Gemini API, Ollama, optional embeddings
- **Automation:** n8n, Playwright (isolated browser-worker service)
- **Data:** PostgreSQL + pgvector
- **Cloud:** AWS (ap-south-1) — EC2 first, then ECS Fargate; Terraform-managed
- **CI/CD:** GitHub Actions with OIDC (no static AWS keys)

## Local development

```bash
cp .env.example .env        # fill in real values — never commit .env
docker compose up --build
```

Set `OPENROUTER_API_KEY` in `.env` to enable optional model-assisted search
intent and resume extraction. The default
`OPENROUTER_MODEL=nvidia/nemotron-3.5-super-vl:free` is a free model with
structured JSON output support. Free-model availability and rate limits vary.
The app falls back to labeled rule-based logic when no provider is set.
Do not paste API keys into source files or commit `.env`.

- Backend: http://localhost:8000 (docs at `/docs`)
- Frontend: http://localhost:3000
- n8n: http://localhost:5678
- Browser worker: http://localhost:8100 (not started by default in prod)

Job discovery uses configured public feeds and career-board APIs. Google,
LinkedIn, and Indeed can also be opened in an isolated, user-controlled search
browser; this does not scrape their pages or bypass sign-in/CAPTCHA controls.
The Nemotron visual browser option sends screenshots to OpenRouter only after
the user opts in, and stops before personal-data entry or final submission.
Add official provider API credentials only where you are authorized to use
them. Form filling stops for login, CAPTCHA, or unsupported required fields.
Every submission remains blocked until the user reviews that specific
application and explicitly approves it.

The root module under `infra/terraform` targets ECS/RDS and can create
cost-incurring NAT Gateway, ALB, RDS, and Fargate resources. It is not a free
deployment. The browser worker defaults to zero ECS tasks while idle. Review
Terraform plans and current AWS pricing before any apply.

## Safety rules this project is built around

- No application is ever submitted without explicit, per-application human approval.
- No job listing is fabricated or marked verified without a real source check.
- No credentials, secrets, or API keys are ever committed — see `.env.example`.
- No CAPTCHA, login, or MFA bypass, ever.
- `terraform destroy` and any billable AWS resource creation require explicit approval first.

## Project structure

```
backend/          FastAPI app, SQLAlchemy models, agents (Phase 7+)
frontend/          Next.js dashboard
browser-worker/    Isolated Playwright automation service
infra/terraform/   AWS infrastructure as code
docs/aws/          Learning docs, one per AWS service used
n8n/               Exported workflow JSON
.github/workflows/ CI and OIDC-based deploy pipeline
```
