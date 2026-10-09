# Project guidance

Preserve the approved architecture in docs/ARCHITECTURE.md and the Italian dashboard guidance in apps/dashboard/AGENTS.md. Runtime processes keep separate database roles and credentials. Trading, external AI and MT5 remain disabled until their respective implementation and acceptance gates pass. Telegram enrollment is an explicit local operator action; source configuration belongs in the authenticated dashboard.

## Living Italian documentation

The user requires two maintained documents: docs/cliente/GUIDA_CLIENTE.md and docs/team/GUIDA_PREPARAZIONE.md, with the matching Word deliverables in those directories. With every feature, operational behavior, environment variable, account requirement or safety-control change, update both guides where relevant. Date the revision in Europe/Rome, append a concise revision entry, distinguish implemented and verified features from configurations still required and future capabilities, and regenerate the Word files. Use the Documents skill and visually verify every rendered page before delivering an updated Word file. Never include actual credentials, session material or personal source messages in examples or artifacts. Keep this update part of the feature work; no recurring automation is implied.
