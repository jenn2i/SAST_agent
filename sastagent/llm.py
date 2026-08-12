"""Anthropic API 래퍼.

토큰 절약 장치 3개가 여기에 들어있다.
  1) prompt caching  : 공통 규칙집(system) 을 cache_control 로 재사용
  2) disk cache      : 같은 코드 해시는 두 번 호출하지 않음
  3) token ledger    : 입력/출력 토큰을 전부 기록해 리포트에 실측치로 남김
offline=True 면 네트워크를 타지 않고 '호출 예정' 만 기록한다(드라이런).
"""

import json
import os
import hashlib
import urllib.request

API_URL = "https://api.anthropic.com/v1/messages"


class TokenLedger:
    def __init__(self):
        self.rows = []

    def add(self, agent, model, usage):
        self.rows.append(dict(agent=agent, model=model, **usage))

    def total(self):
        t = dict(input_tokens=0, output_tokens=0,
                 cache_creation_input_tokens=0, cache_read_input_tokens=0, calls=0)
        for r in self.rows:
            t["calls"] += 1
            for k in list(t):
                if k != "calls":
                    t[k] += r.get(k, 0) or 0
        return t


class LLM:
    def __init__(self, cache_dir="out/.llmcache", offline=False, ledger=None):
        self.cache_dir = cache_dir
        self.offline = offline
        self.ledger = ledger or TokenLedger()
        self.pending = []          # offline 모드에서 '호출했을 프롬프트' 기록
        os.makedirs(cache_dir, exist_ok=True)
        self.key = os.environ.get("ANTHROPIC_API_KEY")

    # -- 캐시 키는 (모델 + system + user) 전체 해시 -------------------------
    def _ck(self, model, system, user):
        h = hashlib.sha256(f"{model}\x00{system}\x00{user}".encode()).hexdigest()
        return os.path.join(self.cache_dir, h + ".json")

    def call(self, agent, model, system, user, max_tokens=800):
        path = self._ck(model, system, user)
        if os.path.exists(path):
            data = json.load(open(path))
            self.ledger.add(agent, model, dict(input_tokens=0, output_tokens=0,
                                               cache_hit=1))
            return data["text"]

        if self.offline or not self.key:
            self.pending.append(dict(agent=agent, model=model, system_len=len(system),
                                     user_len=len(user), user=user))
            return None

        body = dict(
            model=model, max_tokens=max_tokens,
            system=[dict(type="text", text=system,
                         cache_control=dict(type="ephemeral"))],
            messages=[dict(role="user", content=user)],
        )
        req = urllib.request.Request(
            API_URL, data=json.dumps(body).encode(),
            headers={"content-type": "application/json",
                     "x-api-key": self.key,
                     "anthropic-version": "2023-06-01"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            out = json.loads(resp.read())
        text = "".join(b.get("text", "") for b in out.get("content", []))
        self.ledger.add(agent, model, out.get("usage", {}))
        json.dump(dict(text=text), open(path, "w"))
        return text


def parse_json(text: str):
    """모델이 ```json 펜스를 붙여도 안전하게 파싱."""
    if not text:
        return None
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1].rsplit("```", 1)[0]
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        i, j = t.find("{"), t.rfind("}")
        if i >= 0 and j > i:
            try:
                return json.loads(t[i:j + 1])
            except json.JSONDecodeError:
                return None
    return None
