"""
make_synthetic.py — Gera dados sintéticos para testar o pipeline sem dados reais.

Cria data/synthetic.parquet com o mesmo schema do dataset real.
"""
import polars as pl
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta
import random
import hashlib

RANDOM_STATE = 42
N = 5_000
rng = np.random.default_rng(RANDOM_STATE)
random.seed(RANDOM_STATE)

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)

LISTS = [
    "linux-kernel@vger.kernel.org",
    "netdev@vger.kernel.org",
    "linux-mm@kvack.org",
    "linux-fsdevel@vger.kernel.org",
    "linux-usb@vger.kernel.org",
]
AUTHORS = [f"dev{i}@example.com" for i in range(200)]
ACCEPT_TRAILERS = ["Applied", "Acked-by", "Reviewed-by", "Tested-by"]
NEUTRAL_TRAILERS = ["Reported-by", "Suggested-by", "Fixes"]

base_date = datetime(2020, 1, 1)


def make_message_id(i):
    return f"<{hashlib.md5(str(i).encode()).hexdigest()[:12]}@mail.example.com>"


def make_subject(has_patch, is_rfc, version, pos, size):
    tags = []
    if has_patch:
        if version > 1:
            tags.append(f"v{version}")
        if size > 1:
            tags.append(f"{pos:02d}/{size:02d}")
        if is_rfc:
            tags.append("RFC")
        tags.append("PATCH")
    prefix = f"[{' '.join(tags)}] " if tags else ""
    return prefix + random.choice([
        "net: fix null pointer dereference in rx path",
        "mm: improve page allocation efficiency",
        "usb: add support for new device class",
        "fs: fix race condition in inode lookup",
        "sched: reduce latency in CFS scheduler",
    ])


def make_trailers(accepted: bool):
    trailers = []
    if accepted and rng.random() < 0.7:
        t = random.choice(ACCEPT_TRAILERS)
        trailers.append({"attribution": "Maintainer <m@kernel.org>", "identification": t})
    if rng.random() < 0.3:
        t = random.choice(NEUTRAL_TRAILERS)
        trailers.append({"attribution": "Reporter <r@example.com>", "identification": t})
    return trailers


rows = []
msg_ids = [make_message_id(i) for i in range(N)]

for i in range(N):
    is_patch   = rng.random() < 0.75
    is_rfc     = is_patch and rng.random() < 0.1
    version    = int(rng.choice([1,1,1,2,2,3], p=[0.5,0.15,0.1,0.1,0.1,0.05]))
    size       = int(rng.choice(range(1, 20), p=np.ones(19)/19))
    pos        = int(rng.integers(0, max(size, 1)+1))
    author     = random.choice(AUTHORS)
    lst        = random.choice(LISTS)
    date       = base_date + timedelta(
        days=int(rng.integers(0, 365*3)),
        hours=int(rng.integers(0, 24))
    )
    # accepted correlacionado com features (para o modelo ter sinal real)
    p_accept   = 0.3
    if not is_rfc:    p_accept += 0.15
    if version == 1:  p_accept += 0.05
    if size <= 5:     p_accept += 0.10
    accepted   = rng.random() < min(p_accept, 0.9)

    # Threading
    in_reply_to = msg_ids[rng.integers(0, max(i,1))] if i > 0 and rng.random() < 0.4 else None
    refs_len    = int(rng.integers(0, 5))
    refs        = [msg_ids[rng.integers(0, max(i,1))] for _ in range(refs_len)] if i > 0 else []

    rows.append({
        "message_id":               msg_ids[i],
        "from":                     author,
        "to":                       [lst],
        "cc":                       [random.choice(AUTHORS) for _ in range(int(rng.integers(0,5)))],
        "subject":                  make_subject(is_patch, is_rfc, version, pos, size),
        "has_patch_tag":            is_patch,
        "has_rfc_tag":              is_rfc,
        "has_response_tag":         rng.random() < 0.05,
        "has_forward_tag":          rng.random() < 0.02,
        "patch_version":            version if is_patch else None,
        "patchset_sequence_number": f"{pos:02d}/{size:02d}" if is_patch and size > 1 else None,
        "subject_tags":             ["PATCH"] if is_patch else [],
        "untagged_subject":         "fix something",
        "date":                     date,
        "client_date":              [date.isoformat()],
        "in_reply_to":              in_reply_to,
        "references":               refs,
        "x_mailing_list":           lst,
        "trailers":                 make_trailers(accepted),
        "code":                     ["diff --git a/net/core/dev.c b/net/core/dev.c\n+fix"],
        "raw_body":                 "This patch fixes the issue described in commit abc123.",
        "body_sha1":                hashlib.sha1(str(i).encode()).hexdigest(),
        "_source_reference":        f"archive/{lst}/{i}.mbox",
        "list":                     lst,
    })

df = pl.DataFrame(rows)
out = DATA_DIR / "synthetic.parquet"
df.write_parquet(out)
print(f"✓ {N:,} mensagens sintéticas geradas → {out}")
print(f"  Schema: {df.schema}")
