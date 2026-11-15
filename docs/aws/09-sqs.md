# Amazon SQS — Background Job Queues

**Status: planned, not provisioned or wired into the app.** Current API agent
runs use FastAPI background tasks and LangGraph's in-memory checkpoint saver;
they are not durable across process restarts. SQS is a likely next step for
durable job dispatch, but should be added only with a worker consumer,
idempotency, visibility-timeout handling, and a dead-letter queue.

## Why and how it would fit

The API would validate a request, persist an `AgentRun`, then enqueue its ID.
A background worker would claim the message, load the user-owned run, execute
the graph, and delete the message only after recording the result. Use a
separate DLQ for repeated failures. Do not place resume contents or secrets in
messages; use opaque record IDs.

## Permissions and inspection

Create a queue and DLQ in the target account. The producer needs only
`sqs:SendMessage` on the queue. The consumer needs `ReceiveMessage`,
`DeleteMessage`, and `ChangeMessageVisibility` on that queue. Inspect queue
depth, age of oldest message, and DLQ count in the SQS console. Keep queue
encryption enabled and configure retention and visibility timeout for the
longest supported task.

## CLI and Terraform

No queue is defined by the current Terraform root. Once implemented, inspect
with `aws sqs get-queue-attributes --queue-url <queue-url> --attribute-names All`.
Do not create resources from a learning guide without reviewing current AWS
pricing and the Terraform plan. SQS is generally usage priced, while Lambda,
compute, networking, logs, and external services can add costs.

## Troubleshooting and cleanup

If queue age rises, inspect consumer health, IAM, visibility timeout, and DLQ.
Redrive only after fixing the cause. Before deleting a queue, stop producers,
drain or archive messages, and understand that deletion permanently discards
pending work. Current application functionality does not depend on SQS.
