# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6"]
# ///
"""離線檢查技能描述的可區分度：不呼叫任何模型、不耗額度、結果固定。

對每個 evals 情境，用字元二元組＋英數詞的 TF-IDF 餘弦相似度，看它與哪個技能的
name + description 最像（agent 在挑技能時看到的就是這兩個欄位）。回報：
- 應觸發情境：預期技能是否排第一、與第二名的差距（差距小代表描述容易互相混淆）
- 對照情境：最高相似度（應明顯低於應觸發情境）

這只是代理指標：衡量「描述寫得夠不夠有區別」，不等於 agent 真的會載入技能；
實際觸發率仍以 run_evals.py 為準。

用法：uv run scripts/check_descriptions.py [--strict] [--json]
--strict：有任何應觸發情境的預期技能沒排第一就結束碼 1。
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CJK = re.compile(r"[\u3400-\u9fff]")
WORD = re.compile(r"[a-z0-9][a-z0-9.\-_]+", re.I)


def tokens(text: str) -> list[str]:
    text = text.lower()
    out = [w for w in WORD.findall(text)]
    cjk = "".join(c if CJK.match(c) else " " for c in text)
    for chunk in cjk.split():
        out += [chunk[i : i + 2] for i in range(len(chunk) - 1)] or [chunk]
    return out


def load_descriptions() -> dict[str, str]:
    docs = {}
    for skill in sorted((ROOT / "skills").iterdir()):
        head = (skill / "SKILL.md").read_text(encoding="utf-8")[4:].partition("\n---\n")[0]
        meta = yaml.safe_load(head)
        docs[skill.name] = f"{meta['name']} {meta['description']}"
    return docs


def negatives() -> list[str]:
    spec = importlib.util.spec_from_file_location("run_evals", ROOT / "scripts" / "run_evals.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return list(mod.NEGATIVES)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--strict", action="store_true", help="預期技能沒排第一就失敗")
    ap.add_argument("--json", action="store_true", help="輸出 JSON")
    args = ap.parse_args()

    docs = load_descriptions()
    bags = {n: Counter(tokens(t)) for n, t in docs.items()}
    df = Counter(tok for bag in bags.values() for tok in bag)
    idf = {t: math.log((1 + len(bags)) / (1 + c)) + 1 for t, c in df.items()}

    def vec(bag: Counter) -> dict[str, float]:
        v = {t: (1 + math.log(c)) * idf.get(t, 1.0) for t, c in bag.items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        return {t: x / norm for t, x in v.items()}

    dvec = {n: vec(b) for n, b in bags.items()}

    def rank(query: str) -> list[tuple[str, float]]:
        q = vec(Counter(tokens(query)))
        return sorted(((n, sum(w * d.get(t, 0.0) for t, w in q.items())) for n, d in dvec.items()), key=lambda x: -x[1])

    rows = []
    for f in sorted((ROOT / "evals").glob("*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        for c in data["cases"]:
            if c.get("trigger") is False:
                continue
            r = rank(c["query"])
            rows.append({"kind": "positive", "skill": data["skill"], "case": c["id"], "top": r[0][0],
                         "score": round(r[0][1], 3), "margin": round(r[0][1] - r[1][1], 3),
                         "expected_rank": [n for n, _ in r].index(data["skill"]) + 1})
    for i, q in enumerate(negatives(), 1):
        r = rank(q)
        rows.append({"kind": "negative", "skill": "-", "case": f"neg-{i}", "top": r[0][0], "score": round(r[0][1], 3),
                     "margin": 0.0, "expected_rank": 0})

    pos = [r for r in rows if r["kind"] == "positive"]
    neg = [r for r in rows if r["kind"] == "negative"]
    miss = [r for r in pos if r["expected_rank"] != 1]
    summary = {
        "positives": len(pos), "top1": len(pos) - len(miss),
        "min_positive_score": min(r["score"] for r in pos), "max_negative_score": max(r["score"] for r in neg),
        "min_margin": min(r["margin"] for r in pos if r["expected_rank"] == 1) if len(miss) < len(pos) else None,
    }
    if args.json:
        print(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2))
    else:
        print(f"{'類型':<9}{'技能':<26}{'情境':<30}{'名次':<5}{'分數':<7}{'差距':<7}最像")
        for r in rows:
            print(f"{r['kind']:<9}{r['skill']:<26}{r['case']:<30}{r['expected_rank'] or '-':<5}{r['score']:<7}{r['margin']:<7}{r['top']}")
        print(f"\n預期技能排第一：{summary['top1']}/{summary['positives']}；"
              f"應觸發最低分 {summary['min_positive_score']}、對照最高分 {summary['max_negative_score']}")
    return 1 if args.strict and miss else 0


if __name__ == "__main__":
    sys.exit(main())
