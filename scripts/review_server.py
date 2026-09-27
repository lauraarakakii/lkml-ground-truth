#!/usr/bin/env python3
"""Servidor web local e responsivo para validar uma lista integrada.

As respostas são gravadas de modo append-only: uma nova decisão não apaga a
anterior. Ao retomar, a decisão mais recente do mesmo revisor para cada
message_id é considerada, e os itens já respondidos são pulados.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import threading
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


def load_integrated(path: Path) -> list[dict[str, str]]:
    suffix = path.suffix.lower()
    if suffix == ".jsonl":
        with path.open(encoding="utf-8") as source:
            rows = [json.loads(line) for line in source if line.strip()]
    elif suffix == ".csv":
        with path.open(encoding="utf-8", newline="") as source:
            rows = list(csv.DictReader(source))
    elif suffix == ".parquet":
        import polars as pl

        rows = pl.read_parquet(path).to_dicts()
    else:
        raise ValueError("A lista integrada deve ser .jsonl, .csv ou .parquet")
    required = {"message_id", "commit_hash", "github_diff", "lkml_diff"}
    if not rows:
        return []
    missing = required - set(rows[0])
    if missing:
        raise ValueError(f"Campos ausentes na lista integrada: {', '.join(sorted(missing))}")
    ids = [str(row["message_id"]) for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("message_id deve ser único na lista integrada")
    return [{key: str(value) for key, value in row.items()} for row in rows]


class ReviewStore:
    fieldnames = ["recorded_at", "reviewer", "message_id", "commit_hash", "choice"]

    def __init__(self, path: Path, reviewer: str) -> None:
        self.path = path
        self.reviewer = reviewer
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def reviewed_ids(self) -> set[str]:
        if not self.path.exists():
            return set()
        with self.path.open(encoding="utf-8", newline="") as source:
            return {
                row["message_id"]
                for row in csv.DictReader(source)
                if row.get("reviewer") == self.reviewer
                and row.get("choice") in {"match", "no", "partial"}
            }

    def append(self, record: dict[str, str], choice: str) -> None:
        new_file = not self.path.exists() or self.path.stat().st_size == 0
        with self.path.open("a", encoding="utf-8", newline="") as target:
            writer = csv.DictWriter(target, fieldnames=self.fieldnames)
            if new_file:
                writer.writeheader()
            writer.writerow(
                {
                    "recorded_at": datetime.now(UTC).isoformat(),
                    "reviewer": self.reviewer,
                    "message_id": record["message_id"],
                    "commit_hash": record["commit_hash"],
                    "choice": choice,
                }
            )
            target.flush()
            os.fsync(target.fileno())


PAGE = """<!doctype html>
<html lang="pt-BR"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Validação LKML</title>
<style>
body { font:16px system-ui,sans-serif; margin:0; background:#f6f8fa; color:#17202a }
header { padding:1rem 1.25rem; background:#24292f; color:white; position:sticky; top:0 }
main { padding:1rem; max-width:1800px; margin:auto }
.meta { color:#57606a; margin:.5rem 0 1rem }
.diffs { display:grid; grid-template-columns:1fr 1fr; gap:1rem }
.panel { min-width:0 }.panel h2 { font-size:1rem; margin:.2rem 0 .5rem }
pre { margin:0; white-space:pre-wrap; overflow-wrap:anywhere; max-height:68vh;
      overflow:auto; padding:1rem; background:#fff; border:1px solid #d0d7de;
      border-radius:6px; font:12px ui-monospace,monospace }
.buttons { display:flex; gap:.75rem; justify-content:center; padding:1rem;
           position:sticky; bottom:0; background:#f6f8fa }
.buttons button { border:0; border-radius:7px; padding:.8rem 1.5rem; font-weight:700;
                  font-size:1rem; color:white; cursor:pointer }
.match { background:#1a7f37 }.no { background:#cf222e }.partial { background:#bf8700 }
.done { max-width:620px; text-align:center; margin:15vh auto; padding:2rem;
        background:white; border-radius:12px }
@media(max-width:760px) { .diffs { grid-template-columns:1fr }.panel:first-child { margin-bottom:.5rem }
  pre { max-height:38vh }.buttons { gap:.4rem }.buttons button { flex:1; padding:.8rem .3rem } }
</style><body><header><strong>Validação de ground truth</strong>
<span id="progress"></span></header><main id="app"></main>
<script>
const app = document.querySelector('#app');
const progress = document.querySelector('#progress');
function el(tag, text) { const x = document.createElement(tag); x.textContent = text; return x; }
async function load() { const r = await fetch('/api/current'); render(await r.json()); }
function render(data) {
  app.replaceChildren(); progress.textContent = '';
  if (data.complete) { const d = el('section', '🎉 Tudo concluído! Obrigado por validar esta lista.'); d.className = 'done'; app.append(d); return; }
  progress.textContent = ` — ${data.done}/${data.total}`;
  const meta = el('div', `message_id: ${data.record.message_id}  |  commit: ${data.record.commit_hash}`); meta.className = 'meta';
  const diffs = document.createElement('section'); diffs.className = 'diffs';
  for (const [title, diff] of [['Diff LKML5Ws', data.record.lkml_diff], ['Diff GitHub/Linux', data.record.github_diff]]) {
    const panel = document.createElement('article'); panel.className = 'panel'; panel.append(el('h2', title), el('pre', diff)); diffs.append(panel);
  }
  const buttons = document.createElement('div'); buttons.className = 'buttons';
  for (const choice of ['match', 'no', 'partial']) { const b = el('button', choice); b.className = choice; b.onclick = () => save(choice); buttons.append(b); }
  app.append(meta, diffs, buttons);
}
async function save(choice) {
  const r = await fetch('/api/respond', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({choice})});
  if (!r.ok) { alert('Não foi possível salvar. Tente novamente.'); return; }
  render(await r.json());
}
load();
</script></body></html>"""


def make_handler(records: list[dict[str, str]], store: ReviewStore) -> type[BaseHTTPRequestHandler]:
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def send_json(self, data: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def current(self) -> dict[str, Any]:
            reviewed = store.reviewed_ids()
            next_record = next((row for row in records if row["message_id"] not in reviewed), None)
            return {
                "complete": next_record is None,
                "done": len(reviewed & {row["message_id"] for row in records}),
                "total": len(records),
                "record": next_record,
            }

        def do_GET(self) -> None:  # noqa: N802
            if urlparse(self.path).path == "/api/current":
                self.send_json(self.current())
                return
            if urlparse(self.path).path != "/":
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            body = PAGE.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:  # noqa: N802
            if urlparse(self.path).path != "/api/respond":
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                choice = json.loads(self.rfile.read(size)).get("choice")
            except (ValueError, json.JSONDecodeError):
                self.send_json({"error": "Corpo inválido."}, HTTPStatus.BAD_REQUEST)
                return
            if choice not in {"match", "no", "partial"}:
                self.send_json({"error": "Escolha inválida."}, HTTPStatus.BAD_REQUEST)
                return
            with lock:
                state = self.current()
                if state["record"] is None:
                    self.send_json(state)
                    return
                store.append(state["record"], choice)
                self.send_json(self.current())

        def log_message(self, format: str, *args: object) -> None:
            return

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--integrated", type=Path, required=True)
    parser.add_argument("--responses", type=Path, default=Path("output/review_responses.csv"))
    parser.add_argument(
        "--reviewer", required=True, help="Identificador do revisor, por exemplo ana."
    )
    parser.add_argument(
        "--host", default="0.0.0.0", help="Use 127.0.0.1 para acesso apenas local."
    )
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    records = load_integrated(args.integrated)
    handler = make_handler(records, ReviewStore(args.responses, args.reviewer))
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"Abra http://localhost:{args.port} (respostas: {args.responses})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor encerrado.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
