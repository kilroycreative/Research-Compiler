"""Sequential runner for compiler-generated refinement tickets."""

from __future__ import annotations

import asyncio
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RefinementTicket:
    ticket_file: Path
    ticket_id: str
    done: bool


class RefinementQueueRunner:
    """Executes refinement tickets sequentially and marks them complete on success."""

    def __init__(self, queue_root: str | Path) -> None:
        self.queue_root = Path(queue_root).resolve()
        self.tickets_dir = self.queue_root / ".codex-autorunner" / "tickets"

    def load_tickets(self) -> list[RefinementTicket]:
        tickets: list[RefinementTicket] = []
        for ticket_path in sorted(self.tickets_dir.glob("RTICKET-*.md")):
            text = ticket_path.read_text(encoding="utf-8")
            ticket_id = ticket_path.stem.lower()
            done = re.search(r"^done:\s*true\s*$", text, re.MULTILINE) is not None
            tickets.append(RefinementTicket(ticket_file=ticket_path, ticket_id=ticket_id, done=done))
        return tickets

    async def run_command(self, command: str) -> list[dict[str, str]]:
        results: list[dict[str, str]] = []
        for ticket in self.load_tickets():
            if ticket.done:
                continue
            formatted = command.format(ticket=str(ticket.ticket_file), ticket_id=ticket.ticket_id)
            process = await asyncio.to_thread(
                subprocess.run,
                formatted,
                shell=True,
                text=True,
                capture_output=True,
                check=False,
            )
            if process.returncode == 0:
                self._mark_done(ticket.ticket_file)
                status = "ok"
            else:
                status = "failed"
            results.append(
                {
                    "ticket_id": ticket.ticket_id,
                    "status": status,
                    "stdout": process.stdout,
                    "stderr": process.stderr,
                }
            )
            if process.returncode != 0:
                break
        return results

    def _mark_done(self, ticket_file: Path) -> None:
        text = ticket_file.read_text(encoding="utf-8")
        updated = re.sub(r"^done:\s*false\s*$", "done: true", text, count=1, flags=re.MULTILINE)
        ticket_file.write_text(updated, encoding="utf-8")
