from app.services.search_intent import parse_filters
import json
queries = [
 'Find fresher AI Engineer jobs near Bangalore with minimum 8 LPA.',
 'Find GenAI internships with PPO.',
 'Search Python developer jobs in Bengaluru.',
 'Find remote machine learning jobs in India.',
 'Find MCA fresher jobs at product companies.',
 'Find jobs posted in the last 24 hours.',
 'Only remote ones, 12-15 LPA, last 7 days',
]
for q in queries:
    f = parse_filters(q)
    print(q)
    print('  ', {k:v for k,v in f.model_dump().items() if v not in (None, [], False)})
