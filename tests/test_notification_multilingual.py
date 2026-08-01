"""多語通報必須穩定產出四語，或明確降級——不得靜默只給中文。

守的是這個 bug：

    同一起事件（ACC_001，SOP-6 已觸發），連續呼叫兩次
      第一次 → zh / en / ja / ko 四語齊全
      第二次 → 只有 zh，en/ja/ko 全空
    而畫面上、日誌裡都沒有任何跡象顯示發生過什麼。

根因有兩層：
  1. `prompts/notification.txt` 寫「只在漫遊比率達 SOP-6 門檻時產出多語」，
     但**使用者訊息從來沒附漫遊比率**——模型只能自由心證。而 SOP-6 是否觸發，
     規則引擎在呼叫模型之前就已經算出來了。讓模型重新判斷一次已經判定過的事，
     只會製造不一致。
  2. 解析端 `except (JSONDecodeError, KeyError): pass` 把失敗完全吃掉。
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("USE_BEDROCK", "false")

from src import reporting
from src.models import Notification


@pytest.fixture(scope="module")
def ctx():
    from src import orchestrator
    from src.models import RouteRequest

    orchestrator.GATEWAY = orchestrator.build_gateway()
    gw = orchestrator.GATEWAY
    bundle = gw.load_data()
    incident = next(i for i in bundle.incidents if i.event_id == "TPE_2026_ACC_001")
    route_plan = gw.plan_routes(
        RouteRequest(incident=incident, bundle=bundle, as_of=incident.timestamp)
    )
    return incident, route_plan, gw.calculate_ete(incident, bundle), bundle


def test_sop6_is_decided_by_rules_not_the_model(ctx):
    """SOP-6 是否觸發由規則引擎判定——這是前提，不是模型的自由裁量。"""
    from src import orchestrator

    incident, _rp, _ete, bundle = ctx
    sensing = orchestrator.GATEWAY.evaluate_rules(bundle, incident)

    assert sensing.multilingual_required is True
    assert any(h.clause_id == "SOP-6" for h in sensing.rule_hits)


def test_user_message_states_the_decision_explicitly(ctx, monkeypatch):
    """送給模型的訊息必須明說「已判定要四語」，不能讓它自己猜。"""
    incident, route_plan, ete, _bundle = ctx
    captured = {}

    def fake(system_prompt, user_message):
        captured["sys"] = system_prompt
        captured["user"] = user_message
        return '{"zh":"a","en":"b","ja":"c","ko":"d"}'

    monkeypatch.setattr(reporting, "_invoke_bedrock_converse", fake)
    reporting._generate_notification_with_llm(incident, route_plan, ete, True)

    msg = captured["user"]
    assert "SOP-6" in msg, "沒有告訴模型 SOP-6 已觸發"
    assert "必須" in msg
    assert "不得留空" in msg


def test_partial_languages_raise_instead_of_silently_degrading(ctx, monkeypatch):
    """模型只回中文時要拋例外走模板保底，不得靜默回一份殘缺的通報。"""
    incident, route_plan, ete, _bundle = ctx
    monkeypatch.setattr(
        reporting, "_invoke_bedrock_converse",
        lambda s, u: '{"zh": "只有中文"}',
    )

    with pytest.raises(ValueError, match="缺少"):
        reporting._generate_notification_with_llm(incident, route_plan, ete, True)


def test_unparseable_output_raises(ctx, monkeypatch):
    """回傳不是 JSON 時同樣要拋，不能把整段散文塞進 zh 當通報內容。"""
    incident, route_plan, ete, _bundle = ctx
    monkeypatch.setattr(
        reporting, "_invoke_bedrock_converse",
        lambda s, u: "我需要先確認漫遊比率才能決定是否產出多語版本。",
    )

    with pytest.raises(ValueError):
        reporting._generate_notification_with_llm(incident, route_plan, ete, True)


def test_full_four_languages_pass_through(ctx, monkeypatch):
    """四語齊全時原樣回傳。"""
    incident, route_plan, ete, _bundle = ctx
    monkeypatch.setattr(
        reporting, "_invoke_bedrock_converse",
        lambda s, u: '```json\n{"zh":"中","en":"EN","ja":"JA","ko":"KO"}\n```',
    )

    n = reporting._generate_notification_with_llm(incident, route_plan, ete, True)
    assert (n.zh, n.en, n.ja, n.ko) == ("中", "EN", "JA", "KO")


def test_template_fallback_always_gives_four_languages(ctx):
    """模板保底是確定性的，`multilingual=True` 時一定給得出四語。

    這是上面那些例外的接手者——寧可用制式句子，也不要給指揮官一份
    「說好四語但只有中文」的通報。
    """
    incident, route_plan, ete, _bundle = ctx
    n = reporting._generate_c4_fallback(incident, route_plan, ete, True)

    assert isinstance(n, Notification)
    for lang in ("zh", "en", "ja", "ko"):
        assert getattr(n, lang), f"模板保底缺少 {lang}"


def test_single_language_mode_unaffected(ctx, monkeypatch):
    """未觸發 SOP-6 時只要中文，不該因為新的檢查而失敗。"""
    incident, route_plan, ete, _bundle = ctx
    monkeypatch.setattr(reporting, "_invoke_bedrock_converse", lambda s, u: "中文通報內容")

    n = reporting._generate_notification_with_llm(incident, route_plan, ete, False)
    assert n.zh == "中文通報內容"
    assert n.en is None
