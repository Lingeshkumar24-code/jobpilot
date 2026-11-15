from app.services.resume_extractor import extract_profile
import json
text = '''ARJUN SHARMA
AI Engineer | Bengaluru, India
arjun.sharma@example.com | +91 98765 43210
linkedin.com/in/arjunsharma | github.com/arjunsharma

SUMMARY
AI engineer with 3 years of experience building Python and LLM applications.

SKILLS
Python, PyTorch, LangChain, PostgreSQL, Docker, AWS, FastAPI, React

EXPERIENCE
AI Engineer at Acme Technologies | Bengaluru
Jan 2022 - Present
Built RAG pipelines with Python and LangGraph.

Machine Learning Intern - Beta Labs
Jun 2021 - Dec 2021
Trained models with PyTorch.

EDUCATION
B.Tech in Computer Science
National Institute of Technology, Surathkal
2017 - 2021 | CGPA 8.5

PROJECTS
Resume Matcher
Built a FastAPI service using sentence-transformers and pgvector.

CERTIFICATIONS
AWS Certified Cloud Practitioner
'''
p = extract_profile(text)
print(json.dumps(p, indent=2)[:4000])
