# Job search and browser workflow

Last updated: 2026-11-15

## Intended user flow

1. Sign in to JobPilot and enter a request such as **AI jobs in Bengaluru**.
2. Run the app search to see listings returned by configured public feeds. Search sources that require authorized provider APIs remain disabled until credentials are configured.
3. Open Google, LinkedIn, or Indeed in JobPilot's isolated live browser. If the provider asks for sign-in or a CAPTCHA, the user completes it directly in that browser.
4. Optionally allow the current page screenshot to be sent to OpenRouter/Nemotron. The visual agent can then use bounded mouse clicks and scrolling to inspect a listing and reach its application page. It stops before credentials, personal data, uploads, terms acceptance, or final submission.
5. For a listing in JobPilot's result cards, use **Open & fill application** to analyze the employer form. Review the proposed answers in Application Assistant and use the separate approval flow before any submission.

## What was observed locally

- Search intent parsing recognized `AI` and `Bengaluru` for the sample query.
- Remote OK, Arbeitnow, and Remotive returned listings. The final list contained 16 jobs, but several were remote roles in other countries or otherwise not clearly in Bengaluru. Treat the score and location match as needing further validation.
- Google search stopped at Google's CAPTCHA. The agent did not solve it.
- A LinkedIn job search page displayed listings behind a sign-in prompt. No LinkedIn account credentials were entered.
- Indeed returned an access-blocked page in the screenshot capture.
- A Toptal/Remote OK listing's Apply control returned to the listing instead of an employer form. A separate Arbeitnow listing reached a Recruitee page, but the Apply section was not reliably exposed to the form analyzer.
- The JobPilot login session expired during backend restarts. The latest live UI is at the JobPilot sign-in page; the Nemotron mouse path has not been exercised end to end after sign-in.
- No employer application was submitted and no resume was uploaded to an employer in this workflow.

## Implementation and verification

- The search page has direct Google, LinkedIn, and Indeed browser buttons.
- The browser worker accepts bounded mouse and scroll actions in the same Chromium session shown in the live browser panel.
- Nemotron receives a screenshot only after the user checks the screenshot-sharing opt-in. The visual agent has a maximum of six actions per run and stops before obvious final-submit or terms controls.
- Backend and browser-worker Python compilation passed; frontend TypeScript checking passed. The frontend production build passed before a later redundant rebuild was interrupted. The app should be rebuilt once more before release.
- Current local health checks succeeded for the backend and browser worker. AWS deployment, scaling, and production behavior were not tested.

## Screenshots

The screenshots below are fresh, sanitized captures of the observable pages. They show the state reached during the workflow, not a successful application submission.

| Capture | What it shows |
|---|---|
| [JobPilot sign-in](screenshots/01-jobpilot-login.png) | Local app sign-in screen; no credentials are present. |
| [JobPilot search](screenshots/02-jobpilot-search.png) | Search controls while signed out; provider buttons are disabled until sign-in. |
| [Google search challenge](screenshots/03-google-ai-jobs.png) | Google stopped the request for a CAPTCHA; the capture omits request identifiers. |
| [LinkedIn job results](screenshots/04-linkedin-ai-jobs.png) | Public job results behind LinkedIn's sign-in prompt. |
| [Indeed access response](screenshots/05-indeed-ai-jobs.png) | Indeed blocked the automated screenshot request; identifying request details are omitted. |

These are page captures made for this report. They do not replace live verification after signing back in to JobPilot.
