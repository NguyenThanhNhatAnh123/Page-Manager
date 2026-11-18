# PageManager workspaces

- For a Windows server installation or a transferred release, read `SERVER-HANDOFF.md` first.
- This application uses a Rust gateway, Python worker, PostgreSQL and a built React frontend. The chosen server platform is native Windows 11, without WSL, Ubuntu, Hyper-V or Docker.
- Each of the 20 users has a UUID-bound workspace and personal MCP credentials. The displayed non-admin role is **Seller**; the compatible stored/API value remains `owner`.
- Never place real passwords, Meta/MCP tokens, encryption keys, database dumps or operational media in Git. Transfer data using the encrypted archive and a separately supplied key file.
- Preserve the existing 32 completed Reel jobs, their request IDs, checkpoints and video IDs. A transfer must never schedule or publish those videos again.
- Keep the transferred installation in `PM_DEV_READ_ONLY=1` while validating restore, login, media and MCP. Installing services or changing DNS on the separate server is a later server task, not an instruction to modify the dev machine.
- Tests requiring PostgreSQL must use an explicit disposable `PM_TEST_DATABASE_URL`; never run schema-reset fixtures against a restored or operational database.

