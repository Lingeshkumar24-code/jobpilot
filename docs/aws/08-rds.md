# Amazon RDS — Managed PostgreSQL

**Status: Terraform defines private PostgreSQL 16; no live instance verified.** RDS stores user profiles, resumes metadata, jobs, matches, applications, approval records, and audit history. The current Terraform uses a private subnet group, encryption, backups, SSL enforcement, deletion protection, and PostgreSQL log export. Validate the pgvector extension and migration compatibility before enabling production embeddings.

Inspect RDS → Databases → Connectivity/Monitoring/Logs in the Console. CLI read-only inspection: `aws rds describe-db-instances --db-instance-identifier <identifier>`. Application connections use `DATABASE_URL` from SSM SecureString. Only the backend security group should reach port 5432; do not make RDS public.

RDS instance hours, storage, I/O, backup storage, and data transfer incur charges. Check current regional pricing and budget before applying. For connection issues inspect VPC routes, security groups, credentials/URL encoding, SSL, database name, and migrations. Before deleting, take and verify a snapshot and export required data; deletion protection is enabled by default.
