---
name: commit
description: Create a conventional commit following project conventions
argument-hint: "[optional message override]"
disable-model-invocation: true
allowed-tools: Bash(git *)
---

Create a commit following this project's conventions.

## Steps

1. Run `git status` to see changed files (never use `-uall`).
2. Run `git diff` (staged + unstaged) to understand what changed.
3. Run `git log --oneline -5` to see recent commit style.
4. Choose the correct conventional commit prefix based on the changes:

   | Prefix     | When to use                                    |
   |------------|------------------------------------------------|
   | `feat`     | New feature or capability                      |
   | `fix`      | Bug fix                                        |
   | `docs`     | Documentation only                             |
   | `ci`       | CI/CD workflows, GitHub Actions                |
   | `chore`    | Dependencies, config, non-code maintenance     |
   | `refactor` | Code restructuring without behavior change     |
   | `test`     | Adding or updating tests                       |
   | `style`    | Formatting, linting fixes (no logic change)    |
   | `perf`     | Performance improvement                        |

5. If there are no changes to commit, say so and stop.
6. Stage the relevant files by name — do NOT use `git add -A` or `git add .`.
7. Write a commit message:
   - Format: `prefix(scope): short imperative description`
   - Scope is optional — use it when the change targets a specific component (e.g., `fix(store):`, `ci(lint):`)
   - Body explains **why**, not what — the diff shows what changed
   - Do NOT add `Co-Authored-By` lines
8. Commit using a HEREDOC for the message.
9. Run `git status` to verify the commit succeeded.

## Rules

- Never commit `.env`, credentials, or secrets
- Never amend previous commits unless explicitly asked
- Never push — only commit locally
- If `$ARGUMENTS` is provided, use it as guidance for the commit message but still follow the format above
