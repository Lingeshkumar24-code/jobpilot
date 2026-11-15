// Fixture data for the Phase 2 dashboard shell. Nothing here is a real job
// listing or a real agent run — every value is sample data clearly used
// only to prove out the layout, and gets replaced once the matching
// pipeline (Phase 6–8) and agent runs (Phase 7) are wired to the backend.

export const sampleRadar = {
  scannedToday: 128,
  newMatches: 7,
  sourcesActive: 4,
};

export const samplePipeline = {
  awaitingApproval: 4,
  submitted: 2,
  needsInput: 1,
};

export const sampleJobs = [
  {
    id: "1",
    title: "Senior AI Engineer",
    company: "Razorpay",
    location: "Bengaluru · Hybrid",
    matchScore: 87,
    postedDaysAgo: 1,
  },
  {
    id: "2",
    title: "GenAI Engineering Intern",
    company: "Freshworks",
    location: "Remote",
    matchScore: 81,
    postedDaysAgo: 1,
  },
  {
    id: "3",
    title: "Machine Learning Engineer",
    company: "Postman",
    location: "Bengaluru · On-site",
    matchScore: 74,
    postedDaysAgo: 2,
  },
];
