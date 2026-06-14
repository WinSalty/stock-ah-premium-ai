from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.db.base import Base
from app.db.models.auth import AppUser
from app.db.models.chat import LlmCallMetric
from app.db.models.market import ATradeCalendar
from app.db.models.notification import (
    LimitUpAnalysisCache,
    LimitUpPushDelivery,
    LimitUpPushRecipient,
    LimitUpReportShare,
    PushplusBinding,
)
from app.schemas.limit_up_push import LimitUpRecipientUpdateItem, LimitUpRecipientUpdateRequest
from app.services.auth_service import AuthService
from app.services.limit_up_push_service import LimitUpPushError, LimitUpPushService
from app.services.tushare_client import TushareResult


class FakeTushareClient:
    """打板推送测试用 Tushare 客户端。

    创建日期：2026-05-08
    author: sunshengxian
    """

    def __init__(self, rows_by_api: dict[object, list[dict[str, object]]]) -> None:
        self.rows_by_api = rows_by_api
        self.calls: list[tuple[str, dict[str, object]]] = []

    def query(
        self,
        api_name: str,
        params: dict[str, object] | None = None,
        fields: list[str] | None = None,
    ) -> TushareResult:
        normalized_params = params or {}
        self.calls.append((api_name, normalized_params))
        tag = normalized_params.get("tag")
        trade_date = normalized_params.get("trade_date")
        rows = (
            self.rows_by_api.get((api_name, trade_date, tag))
            or self.rows_by_api.get((api_name, tag))
            or self.rows_by_api.get((api_name, trade_date))
            or self.rows_by_api.get(api_name)
            or []
        )
        return TushareResult(fields=fields or [], rows=rows)


class FakeNotificationService:
    """打板推送测试用 PushPlus 服务。

    创建日期：2026-05-08
    author: sunshengxian
    """

    def __init__(self) -> None:
        self.sent: list[tuple[int, str, str]] = []

    def can_send_pushplus_to_user(self, user_id: int) -> bool:
        return True

    def send_pushplus_message(
        self, user_id: int, title: str, content: str, alert_event_id: int | None = None
    ) -> str:
        self.sent.append((user_id, title, content))
        return f"msg-{len(self.sent)}"


def make_db() -> Session:
    """创建内存数据库会话。

    创建日期：2026-05-08
    author: sunshengxian
    """

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def _compact_service() -> LimitUpPushService:
    """构造一个仅用于测试纯计算方法(_compact_stock_row 等)的轻量 service。"""
    return LimitUpPushService(
        make_db(),
        settings=Settings(llm_api_key_file=None, tushare_token="token", tushare_token_file=None),
        tushare_client=FakeTushareClient({}),
        notification_service=FakeNotificationService(),
    )


def test_compact_stock_row_seal_ratio_unit_consistency():
    """评审 P0-F2：封流比分母 free_float(元) 缺失回退 circ_mv(万元) 时必须 ×10000 换算，
    否则分母被缩小 1e4、封流比被放大约 1 万倍。"""
    svc = _compact_service()
    # (a) free_float 直接给（元）：1e7 封单 / 1e9 流通 = 1.0%
    ra = svc._compact_stock_row({"ts_code": "600000.SH", "limit_order": 1e7, "free_float": 1e9}, {})
    assert ra["seal_ratio_pct"] == pytest.approx(1.0, abs=1e-6)
    # (b) free_float 缺失，回退 circ_mv=1e5(万元=1e9元)：应同为 1.0%，而非 10000%
    rb = svc._compact_stock_row({"ts_code": "600000.SH", "limit_order": 1e7}, {"circ_mv": 1e5})
    assert rb["seal_ratio_pct"] == pytest.approx(1.0, abs=1e-6)


def test_compact_stock_row_seal_ratio_over_100_capped():
    """封流比 >100%(单位错配/脏数据：封单>流通市值) → 置缺(None)，不静默落表污染打分。"""
    svc = _compact_service()
    r = svc._compact_stock_row({"ts_code": "600000.SH", "limit_order": 1e9, "free_float": 1e7}, {})
    assert r["seal_ratio_pct"] is None


def add_user(db: Session) -> AppUser:
    """写入可接收打板推送的测试用户。

    创建日期：2026-05-08
    author: sunshengxian
    """

    user = AppUser(username="limit-user", password_hash="hash", role="USER", is_active=True)
    db.add(user)
    db.flush()
    db.add(
        PushplusBinding(
            user_id=user.id,
            friend_id=1001,
            friend_token="friend-token",
            is_follow=True,
            is_active=True,
            bound_at=datetime.now(UTC).replace(tzinfo=None),
        )
    )
    db.add(LimitUpPushRecipient(user_id=user.id, enabled=True))
    db.commit()
    db.refresh(user)
    return user


def test_latest_trade_date_uses_previous_trade_day_for_kpl() -> None:
    """确认早盘 KPL 任务读取今天之前的最近交易日。

    创建日期：2026-05-08
    author: sunshengxian
    """

    db = make_db()
    db.add_all(
        [
            ATradeCalendar(exchange="SSE", cal_date=date(2026, 5, 8), is_open=1),
            ATradeCalendar(exchange="SSE", cal_date=date(2026, 5, 11), is_open=1),
        ]
    )
    db.commit()
    service = LimitUpPushService(
        db,
        settings=Settings(
            llm_api_key=None,
            llm_api_key_file=None,
            tushare_token="token",
            tushare_token_file=None,
        ),
        tushare_client=FakeTushareClient({}),
        notification_service=FakeNotificationService(),
    )

    assert service.latest_a_trade_date(date(2026, 5, 11)) == date(2026, 5, 8)


def test_limit_up_analysis_waits_for_kpl_data() -> None:
    """确认 KPL 数据未更新时不生成报告。

    创建日期：2026-05-08
    author: sunshengxian
    """

    db = make_db()
    db.add(ATradeCalendar(exchange="SSE", cal_date=date(2026, 5, 8), is_open=1))
    db.commit()
    service = LimitUpPushService(
        db,
        settings=Settings(
            llm_api_key=None,
            llm_api_key_file=None,
            tushare_token="token",
            tushare_token_file=None,
        ),
        tushare_client=FakeTushareClient({}),
        notification_service=FakeNotificationService(),
    )

    assert service.ensure_analysis_for_trade_date(date(2026, 5, 8)) is None
    assert db.scalar(select(LimitUpAnalysisCache)) is None


def test_limit_up_report_cache_reuses_same_snapshot(monkeypatch) -> None:
    """确认同一 KPL 快照只调用一次 LLM 并复用报告缓存。

    创建日期：2026-05-08
    author: sunshengxian
    """

    db = make_db()
    fake_client = FakeTushareClient(
        {
            "kpl_list": [
                {
                    "ts_code": "000001.SZ",
                    "name": "测试股份",
                    "trade_date": "20260508",
                    "status": "2连板",
                    "theme": "人工智能",
                    "lu_desc": "AI 应用催化",
                }
            ]
        }
    )
    service = LimitUpPushService(
        db,
        settings=Settings(
            llm_api_key="key",
            llm_api_key_file=None,
            tushare_token="token",
            tushare_token_file=None,
        ),
        tushare_client=fake_client,
        notification_service=FakeNotificationService(),
    )
    calls: list[dict[str, object]] = []

    def fake_generate(context: dict[str, object]) -> tuple[str, str]:
        calls.append(context)
        return "<h2>报告</h2>", "报告"

    monkeypatch.setattr(service, "_generate_llm_report", fake_generate)

    first = service.ensure_analysis_for_trade_date(date(2026, 5, 8))
    second = service.ensure_analysis_for_trade_date(date(2026, 5, 8))

    assert first is not None
    assert second is not None
    assert first.id == second.id
    assert len(calls) == 1
    assert first.status == "READY"


def test_limit_up_failed_snapshot_retries_same_cache(monkeypatch) -> None:
    """确认同一数据快照首次生成失败后，后续轮询复用原缓存记录重试。

    创建日期：2026-06-02
    author: sunshengxian
    """

    db = make_db()
    service = LimitUpPushService(
        db,
        settings=Settings(
            llm_api_key="key",
            llm_api_key_file=None,
            tushare_token="token",
            tushare_token_file=None,
        ),
        tushare_client=FakeTushareClient(
            {
                "kpl_list": [
                    {
                        "ts_code": "000001.SZ",
                        "name": "测试股份",
                        "trade_date": "20260508",
                        "status": "2连板",
                        "theme": "人工智能",
                        "lu_desc": "AI 应用催化",
                    }
                ]
            }
        ),
        notification_service=FakeNotificationService(),
    )
    calls = 0

    def flaky_generate(context: dict[str, object]) -> tuple[str, str]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("模型网关临时异常")
        return "<h2>重试成功</h2>", "重试成功"

    monkeypatch.setattr(service, "_generate_llm_report", flaky_generate)

    with pytest.raises(RuntimeError):
        service.ensure_analysis_for_trade_date(date(2026, 5, 8))
    failed = db.scalar(select(LimitUpAnalysisCache))
    assert failed is not None
    assert failed.status == "FAILED"

    retried = service.ensure_analysis_for_trade_date(date(2026, 5, 8))

    assert retried is not None
    assert retried.id == failed.id
    assert retried.status == "READY"
    assert retried.error_message is None
    assert calls == 2


def test_limit_up_snapshot_hash_is_stable_for_row_order() -> None:
    """确认快照哈希不受列表行序扰动影响。

    创建日期：2026-06-10
    author: sunshengxian
    """

    db = make_db()
    service = LimitUpPushService(
        db,
        settings=Settings(
            llm_api_key="key",
            llm_api_key_file=None,
            tushare_token="token",
            tushare_token_file=None,
        ),
        tushare_client=FakeTushareClient({}),
        notification_service=FakeNotificationService(),
    )
    left = {
        "trade_date": "2026-05-08",
        "limit_up_stocks": [
            {"ts_code": "000002.SZ", "trade_date": "2026-05-08", "name": "乙"},
            {"ts_code": "000001.SZ", "trade_date": "2026-05-08", "name": "甲"},
        ],
    }
    right = {
        "trade_date": "2026-05-08",
        "limit_up_stocks": [
            {"ts_code": "000001.SZ", "trade_date": "2026-05-08", "name": "甲"},
            {"ts_code": "000002.SZ", "trade_date": "2026-05-08", "name": "乙"},
        ],
    }

    assert service._snapshot_hash(left) == service._snapshot_hash(right)


def test_limit_up_report_cache_reuses_ready_when_snapshot_order_changes(monkeypatch) -> None:
    """确认早盘轮询已有 READY 报告时不因接口行序变化重新生成。

    创建日期：2026-06-10
    author: sunshengxian
    """

    db = make_db()
    db.add(ATradeCalendar(exchange="SSE", cal_date=date(2026, 5, 8), is_open=1))
    db.commit()
    user = add_user(db)
    fake_notification = FakeNotificationService()
    fake_client = FakeTushareClient(
        {
            "kpl_list": [
                {
                    "ts_code": "000002.SZ",
                    "name": "测试乙",
                    "trade_date": "20260508",
                    "status": "2连板",
                    "tag": "涨停",
                },
                {
                    "ts_code": "000001.SZ",
                    "name": "测试甲",
                    "trade_date": "20260508",
                    "status": "首板",
                    "tag": "涨停",
                },
            ]
        }
    )
    service = LimitUpPushService(
        db,
        settings=Settings(
            llm_api_key="key",
            llm_api_key_file=None,
            tushare_token="token",
            tushare_token_file=None,
            # 回滚通道回归：REPORT 模式必须与重构前推送行为一致（不触发建议生成）。
            limit_up_push_content_mode="REPORT",
        ),
        tushare_client=fake_client,
        notification_service=fake_notification,
    )
    calls = 0

    def fake_generate(context: dict[str, object]) -> tuple[str, str]:
        nonlocal calls
        calls += 1
        return "<h2>报告</h2>", "报告"

    monkeypatch.setattr(service, "_today_local", lambda: date(2026, 5, 9))
    monkeypatch.setattr(service, "_generate_llm_report", fake_generate)
    monkeypatch.setattr(service, "_latest_pushplus_log_id", lambda user_id, message_id: None)

    first_analysis, first_pushed = service.ensure_latest_analysis_and_push()
    fake_client.rows_by_api["kpl_list"] = list(reversed(fake_client.rows_by_api["kpl_list"]))
    second_analysis, second_pushed = service.ensure_latest_analysis_and_push()

    assert first_analysis is not None
    assert second_analysis is not None
    assert first_analysis.id == second_analysis.id
    assert calls == 1
    assert first_pushed == 1
    assert second_pushed == 0
    assert fake_notification.sent == [(user.id, "2026-05-08 A股涨停打板复盘", "<h2>报告</h2>")]


def test_limit_up_stale_generating_snapshot_retries(monkeypatch) -> None:
    """确认僵死 GENERATING 报告超过阈值后会复用原记录重跑。

    创建日期：2026-06-10
    author: sunshengxian
    """

    db = make_db()
    service = LimitUpPushService(
        db,
        settings=Settings(
            llm_api_key="key",
            llm_api_key_file=None,
            tushare_token="token",
            tushare_token_file=None,
            limit_up_push_generating_stale_minutes=30,
        ),
        tushare_client=FakeTushareClient(
            {
                "kpl_list": [
                    {
                        "ts_code": "000001.SZ",
                        "name": "测试股份",
                        "trade_date": "20260508",
                        "status": "2连板",
                        "tag": "涨停",
                    }
                ]
            }
        ),
        notification_service=FakeNotificationService(),
    )
    stale = LimitUpAnalysisCache(
        trade_date=date(2026, 5, 8),
        model="deepseek-v4-pro",
        prompt_version="limit-up-v1",
        data_snapshot_hash=service._snapshot_hash(
            service._build_context_snapshot(date(2026, 5, 8))["context"]
        ),
        status="GENERATING",
        title="旧报告",
    )
    db.add(stale)
    db.commit()
    db.refresh(stale)
    stale.updated_at = datetime(2026, 5, 8, 8, 0, 0)
    db.commit()
    monkeypatch.setattr(service, "_now_naive", lambda: datetime(2026, 5, 8, 8, 40, 0))
    monkeypatch.setattr(service, "_generate_llm_report", lambda context: ("<h2>重跑</h2>", "重跑"))

    retried = service.ensure_analysis_for_trade_date(date(2026, 5, 8))

    assert retried is not None
    assert retried.id == stale.id
    assert retried.status == "READY"
    assert retried.content_html == "<h2>重跑</h2>"


def test_limit_up_recent_generating_snapshot_is_not_reset(monkeypatch) -> None:
    """确认未超过阈值的 GENERATING 报告不会因数据库时区差异被误判僵死。

    创建日期：2026-06-11
    author: sunshengxian
    """

    db = make_db()
    service = LimitUpPushService(
        db,
        settings=Settings(
            llm_api_key="key",
            llm_api_key_file=None,
            tushare_token="token",
            tushare_token_file=None,
            limit_up_push_generating_stale_minutes=30,
        ),
        tushare_client=FakeTushareClient(
            {
                "kpl_list": [
                    {
                        "ts_code": "000001.SZ",
                        "name": "测试股份",
                        "trade_date": "20260508",
                        "status": "2连板",
                        "tag": "涨停",
                    }
                ]
            }
        ),
        notification_service=FakeNotificationService(),
    )
    context = service._build_context_snapshot(date(2026, 5, 8))["context"]
    generating = LimitUpAnalysisCache(
        trade_date=date(2026, 5, 8),
        model="deepseek-v4-pro",
        prompt_version="limit-up-v1",
        data_snapshot_hash=service._snapshot_hash(context),
        status="GENERATING",
        title="生成中报告",
        updated_at=datetime(2026, 5, 8, 0, 20, 0),
    )
    db.add(generating)
    db.commit()
    db.refresh(generating)
    monkeypatch.setattr(service, "_now_naive", lambda: datetime(2026, 5, 8, 0, 40, 0))
    monkeypatch.setattr(
        service,
        "_generate_llm_report",
        lambda context: (_ for _ in ()).throw(AssertionError("不应重跑")),
    )

    current = service.ensure_analysis_for_trade_date(date(2026, 5, 8))

    assert current is not None
    assert current.id == generating.id
    assert current.status == "GENERATING"


def test_limit_up_market_emotion_uses_explicit_levels_and_cycle_metrics() -> None:
    """确认情绪统计使用显式板高并计算炸板率、晋级率和昨日溢价。

    创建日期：2026-06-10
    author: sunshengxian
    """

    db = make_db()
    service = LimitUpPushService(
        db,
        settings=Settings(
            llm_api_key="key",
            llm_api_key_file=None,
            tushare_token="token",
            tushare_token_file=None,
        ),
        tushare_client=FakeTushareClient({}),
        notification_service=FakeNotificationService(),
    )
    today_rows = [
        {"ts_code": "000001.SZ", "status": "2连板", "tag": "涨停"},
        {"ts_code": "000002.SZ", "status": "3连板", "tag": "涨停"},
        {"ts_code": "000003.SZ", "status": "12连板", "tag": "涨停"},
        {"ts_code": "000004.SZ", "status": "3天2板", "tag": "涨停"},
        {"ts_code": "000005.SZ", "tag": "涨停"},
    ]
    prev_rows = [
        {"ts_code": "000001.SZ", "status": "首板", "tag": "涨停"},
        {"ts_code": "000002.SZ", "status": "2连板", "tag": "涨停"},
    ]
    emotion = service._market_emotion(
        today_rows,
        {
            "kpl_list_炸板": [
                {"ts_code": "000001.SZ", "status": "炸板回封", "tag": "炸板"},
                {"ts_code": "000099.SZ", "status": "炸板", "tag": "炸板"},
            ],
            "kpl_list_跌停": [{"ts_code": "000098.SZ", "status": "跌停", "tag": "跌停"}],
            "prev_kpl_list": prev_rows,
            "prev_trade_date": [{"trade_date": "2026-05-07"}],
        },
        {
            "000001.SZ": {"open": 11, "pre_close": 10, "pct_chg": 5},
            "000002.SZ": {"open": 9, "pre_close": 10, "pct_chg": -2},
        },
    )

    assert emotion["limit_up_count"] == 5
    assert emotion["second_board_count"] == 2
    assert emotion["third_board_count"] == 1
    assert emotion["highest_chain"] == 12
    assert emotion["unrecognized_board_count"] == 1
    assert emotion["limit_down_count"] == 1
    assert emotion["emotion_cycle"]["broken_board_unique_count"] == 2
    assert emotion["emotion_cycle"]["broken_board_only_count"] == 1
    assert emotion["emotion_cycle"]["limit_up_or_broken_unique_count"] == 6
    assert emotion["emotion_cycle"]["broken_board_rate_pct"] == pytest.approx(16.666667)
    assert emotion["emotion_cycle"]["advancement"]["1进2"]["rate_pct"] == 100.0
    assert emotion["emotion_cycle"]["prev_limit_up_premium"]["quote_sample_count"] == 2
    assert emotion["emotion_cycle"]["prev_limit_up_premium"]["high_open_rate_pct"] == 50.0


def test_limit_up_json_stage_requests_json_mode(monkeypatch) -> None:
    """确认 JSON 阶段调用模型时开启 response_format json_object。

    创建日期：2026-06-10
    author: sunshengxian
    """

    db = make_db()
    captured: list[bool] = []
    service = LimitUpPushService(
        db,
        settings=Settings(
            llm_api_key="key",
            llm_api_key_file=None,
            tushare_token="token",
            tushare_token_file=None,
        ),
        tushare_client=FakeTushareClient({}),
        notification_service=FakeNotificationService(),
    )

    def fake_chat(prompt: str, system_prompt: str, json_mode: bool = False) -> str:
        captured.append(json_mode)
        return '{"selected_stocks": []}'

    monkeypatch.setattr(service, "_chat_completion_with_reasoning", fake_chat)
    service._run_json_stage(
        "CHAIN_SELECTION",
        {"trade_date": "2026-05-08"},
        "system",
        "user",
        {"selected_stocks": []},
        [],
    )

    assert captured == [True]


def test_limit_up_focus_text_stage_falls_back_on_llm_error(monkeypatch) -> None:
    """确认重点文本阶段失败时降级为确定性 HTML，不阻断最终合成。

    创建日期：2026-06-10
    author: sunshengxian
    """

    db = make_db()
    service = LimitUpPushService(
        db,
        settings=Settings(
            llm_api_key="key",
            llm_api_key_file=None,
            tushare_token="token",
            tushare_token_file=None,
        ),
        tushare_client=FakeTushareClient({}),
        notification_service=FakeNotificationService(),
    )
    monkeypatch.setattr(
        service,
        "_chat_completion_with_reasoning",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("模型异常")),
    )
    stage_quality: list[dict[str, object]] = []

    payload = service._run_text_stage(
        "CHAIN_FOCUS",
        {
            "trade_date": "2026-05-08",
            "selected_chain_stocks": [
                {
                    "ts_code": "000001.SZ",
                    "name": "测试股份",
                    "status": "2连板",
                    "theme": "人工智能",
                    "selection": {"selection_reason": "板块前排"},
                }
            ],
            "supplements": {"000001.SZ": {"cyq_summary": {"next_day_premium_bias": "偏友好"}}},
        },
        "system",
        "user",
        stage_quality,
    )

    assert payload["error_fallback"] is True
    assert "LLM 重点分析不可用" in payload["html_fragment"]
    assert stage_quality[0]["status"] == "FAILED_FALLBACK"


def test_limit_up_focus_codes_use_board_level_for_multi_day_board() -> None:
    """确认 N天M板股票会按板高识别进入技术补数范围。

    创建日期：2026-06-11
    author: sunshengxian
    """

    db = make_db()
    service = LimitUpPushService(
        db,
        settings=Settings(
            llm_api_key="key",
            llm_api_key_file=None,
            tushare_token="token",
            tushare_token_file=None,
        ),
        tushare_client=FakeTushareClient({}),
        notification_service=FakeNotificationService(),
    )

    codes = service._focus_ts_codes(
        [
            {"ts_code": "000001.SZ", "status": "5天3板", "tag": "涨停"},
            {"ts_code": "000002.SZ", "status": "普通涨停", "tag": "涨停"},
        ],
        {},
    )

    assert codes == ["000001.SZ"]


def test_limit_up_report_list_marks_stage_fallback() -> None:
    """确认列表项暴露阶段降级标识，便于管理员判断是否手动重跑。

    创建日期：2026-06-11
    author: sunshengxian
    """

    db = make_db()
    analysis = LimitUpAnalysisCache(
        trade_date=date(2026, 5, 8),
        model="deepseek-v4-pro",
        prompt_version="limit-up-v1",
        data_snapshot_hash="hash",
        status="READY",
        title="报告",
        content_html="<h2>报告</h2>",
        context_json=(
            '{"pipeline":{"stage_quality":[{"stage_key":"CHAIN_FOCUS","status":"FAILED_FALLBACK","message":"模型异常"}]}}'
        ),
    )
    db.add(analysis)
    db.commit()
    service = LimitUpPushService(
        db,
        settings=Settings(
            llm_api_key="key",
            llm_api_key_file=None,
            tushare_token="token",
            tushare_token_file=None,
        ),
        tushare_client=FakeTushareClient({}),
        notification_service=FakeNotificationService(),
    )

    items = service.list_reports()
    detail = service.get_report(analysis.id)

    assert items[0].has_stage_fallback is True
    assert detail.has_stage_fallback is True


def test_limit_up_llm_error_response_is_recorded(monkeypatch) -> None:
    """确认 DeepSeek 非 choices 错误体会写入指标，便于排查真实上游响应。

    创建日期：2026-06-02
    author: sunshengxian
    """

    class FakeResponse:
        status_code = 200
        text = '{"error":{"message":"模型网关返回错误","code":"upstream_error"}}'

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "error": {
                    "message": "模型网关返回错误",
                    "code": "upstream_error",
                }
            }

    class FakeClient:
        def __init__(self, timeout: float) -> None:
            self.timeout = timeout

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
            return None

        def post(
            self,
            url: str,
            headers: dict[str, str],
            json: dict[str, object],
        ) -> FakeResponse:
            return FakeResponse()

    db = make_db()
    service = LimitUpPushService(
        db,
        settings=Settings(
            llm_api_key="key",
            llm_api_key_file=None,
            tushare_token="token",
            tushare_token_file=None,
        ),
        tushare_client=FakeTushareClient({}),
        notification_service=FakeNotificationService(),
    )
    monkeypatch.setattr("app.services.limit_up_push_service.httpx.Client", FakeClient)

    with pytest.raises(LimitUpPushError, match="模型网关返回错误"):
        service._chat_completion_with_reasoning("用户提示词", "系统提示词")
    metric = db.scalar(
        select(LlmCallMetric).where(LlmCallMetric.phase == "limit_up_analysis")
    )

    assert metric is not None
    assert metric.success == 0
    assert metric.response_content is not None
    assert "模型网关返回错误" in metric.response_content
    assert metric.error_message is not None
    assert "status=200" in metric.error_message


def test_limit_up_context_filters_st_stocks(monkeypatch) -> None:
    """确认打板报告上下文过滤 ST 风险警示股票。

    创建日期：2026-06-01
    author: sunshengxian
    """

    db = make_db()
    service = LimitUpPushService(
        db,
        settings=Settings(
            llm_api_key="key",
            llm_api_key_file=None,
            tushare_token="token",
            tushare_token_file=None,
        ),
        tushare_client=FakeTushareClient(
            {
                "kpl_list": [
                    {
                        "ts_code": "000001.SZ",
                        "name": "测试股份",
                        "trade_date": "20260508",
                        "status": "2连板",
                        "theme": "人工智能",
                        "lu_desc": "AI 应用催化",
                    },
                    {
                        "ts_code": "000002.SZ",
                        "name": "*ST测试",
                        "trade_date": "20260508",
                        "status": "首板",
                        "theme": "摘帽预期",
                        "lu_desc": "风险警示股异动",
                    },
                ],
                "limit_step": [
                    {
                        "ts_code": "000002.SZ",
                        "name": "*ST测试",
                        "trade_date": "20260508",
                        "nums": "1连",
                    },
                    {
                        "ts_code": "000001.SZ",
                        "name": "测试股份",
                        "trade_date": "20260508",
                        "nums": "2连",
                    },
                ],
                "top_list": [
                    {
                        "ts_code": "000002.SZ",
                        "name": "*ST测试",
                        "trade_date": "20260508",
                        "net_amount": 1000,
                    }
                ],
            }
        ),
        notification_service=FakeNotificationService(),
    )
    captured: list[dict[str, object]] = []

    def fake_generate(context: dict[str, object]) -> tuple[str, str]:
        captured.append(context)
        return "<h2>报告</h2>", "报告"

    monkeypatch.setattr(service, "_generate_llm_report", fake_generate)

    analysis = service.ensure_analysis_for_trade_date(date(2026, 5, 8))

    assert analysis is not None
    assert captured
    context = captured[0]
    assert [row["name"] for row in context["limit_up_stocks"]] == ["测试股份"]
    assert [row["name"] for row in context["raw_supplement"]["limit_step"]] == ["测试股份"]
    assert context["raw_supplement"]["top_list"] == []
    assert any(
        item["api_name"] == "kpl_list" and item["message"] == "raw_rows=2; st_filtered=1"
        for item in context["data_quality"]
    )


def test_limit_up_push_uses_enabled_system_users(monkeypatch) -> None:
    """确认推送只面向启用的系统用户配置。

    创建日期：2026-05-08
    author: sunshengxian
    """

    db = make_db()
    user = add_user(db)
    fake_notification = FakeNotificationService()
    service = LimitUpPushService(
        db,
        settings=Settings(
            llm_api_key="key",
            llm_api_key_file=None,
            tushare_token="token",
            tushare_token_file=None,
            # 回滚通道回归：REPORT 模式必须与重构前推送行为一致（不触发建议生成）。
            limit_up_push_content_mode="REPORT",
        ),
        tushare_client=FakeTushareClient({}),
        notification_service=fake_notification,
    )
    analysis = LimitUpAnalysisCache(
        trade_date=date(2026, 5, 8),
        model="deepseek-v4-pro",
        prompt_version="limit-up-v1",
        data_snapshot_hash="hash",
        status="READY",
        title="打板报告",
        content_html="<h2>报告</h2>",
        generated_at=datetime.now(UTC).replace(tzinfo=None),
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)
    monkeypatch.setattr(service, "_latest_pushplus_log_id", lambda user_id, message_id: None)

    pushed = service.push_report(analysis.id, "MANUAL", datetime.now(UTC).replace(tzinfo=None))

    assert pushed == 1
    assert fake_notification.sent == [(user.id, "打板报告", "<h2>报告</h2>")]


def test_weekend_replay_respects_recipient_preference(monkeypatch) -> None:
    """确认周末晚间复推按接收人独立开关过滤。

    创建日期：2026-05-09
    author: sunshengxian
    """

    db = make_db()
    enabled_user = add_user(db)
    disabled_user = AppUser(
        username="weekend-off", password_hash="hash", role="USER", is_active=True
    )
    db.add(disabled_user)
    db.flush()
    db.add(
        LimitUpPushRecipient(user_id=disabled_user.id, enabled=True, weekend_replay_enabled=False)
    )
    analysis = LimitUpAnalysisCache(
        trade_date=date(2026, 5, 8),
        model="deepseek-v4-pro",
        prompt_version="limit-up-v1",
        data_snapshot_hash="hash",
        status="READY",
        title="周五打板报告",
        content_html="<h2>报告</h2>",
        generated_at=datetime.now(UTC).replace(tzinfo=None),
    )
    db.add(analysis)
    db.commit()
    fake_notification = FakeNotificationService()
    service = LimitUpPushService(
        db,
        settings=Settings(
            llm_api_key="key",
            llm_api_key_file=None,
            tushare_token="token",
            tushare_token_file=None,
            # 回滚通道回归：REPORT 模式必须与重构前推送行为一致（不触发建议生成）。
            limit_up_push_content_mode="REPORT",
        ),
        tushare_client=FakeTushareClient({}),
        notification_service=fake_notification,
    )
    monkeypatch.setattr(service, "_today_local", lambda: date(2026, 5, 9))
    monkeypatch.setattr(service, "_latest_pushplus_log_id", lambda user_id, message_id: None)

    replay_analysis, pushed = service.push_weekend_replay()

    assert replay_analysis is not None
    assert pushed == 1
    assert fake_notification.sent == [(enabled_user.id, "周五打板报告", "<h2>报告</h2>")]


def test_limit_up_push_only_targets_configured_recipients(monkeypatch) -> None:
    """确认手动指定推送也不能绕过启用接收人白名单。

    创建日期：2026-05-08
    author: sunshengxian
    """

    db = make_db()
    user = add_user(db)
    other_user = AppUser(username="other-user", password_hash="hash", role="USER", is_active=True)
    db.add(other_user)
    fake_notification = FakeNotificationService()
    analysis = LimitUpAnalysisCache(
        trade_date=date(2026, 5, 8),
        model="deepseek-v4-pro",
        prompt_version="limit-up-v1",
        data_snapshot_hash="hash",
        status="READY",
        title="打板报告",
        content_html="<h2>报告</h2>",
        generated_at=datetime.now(UTC).replace(tzinfo=None),
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)
    service = LimitUpPushService(
        db,
        settings=Settings(
            llm_api_key="key",
            llm_api_key_file=None,
            tushare_token="token",
            tushare_token_file=None,
            # 回滚通道回归：REPORT 模式必须与重构前推送行为一致（不触发建议生成）。
            limit_up_push_content_mode="REPORT",
        ),
        tushare_client=FakeTushareClient({}),
        notification_service=fake_notification,
    )
    monkeypatch.setattr(service, "_latest_pushplus_log_id", lambda user_id, message_id: None)

    pushed = service.push_report(
        analysis.id,
        "MANUAL",
        datetime.now(UTC).replace(tzinfo=None),
        target_user_ids=[user.id, other_user.id],
    )

    assert pushed == 1
    assert fake_notification.sent == [(user.id, "打板报告", "<h2>报告</h2>")]


def test_update_recipients_syncs_limit_up_menu_permission() -> None:
    """确认管理员启停接收人时同步打板推送菜单权限。

    创建日期：2026-05-08
    author: sunshengxian
    """

    db = make_db()
    admin = AppUser(username="admin", password_hash="hash", role="ADMIN", is_active=True)
    user = AppUser(
        username="receiver",
        password_hash="hash",
        role="USER",
        is_active=True,
        menu_permissions_json='["overview","profile"]',
    )
    db.add_all([admin, user])
    db.commit()
    db.refresh(user)
    service = LimitUpPushService(
        db,
        settings=Settings(
            llm_api_key="key",
            llm_api_key_file=None,
            tushare_token="token",
            tushare_token_file=None,
        ),
        tushare_client=FakeTushareClient({}),
        notification_service=FakeNotificationService(),
    )

    service.update_recipients(
        LimitUpRecipientUpdateRequest(
            recipients=[
                LimitUpRecipientUpdateItem(
                    user_id=user.id, enabled=True, weekend_replay_enabled=False
                )
            ]
        ),
        admin,
    )
    db.refresh(user)
    config = db.scalar(select(LimitUpPushRecipient).where(LimitUpPushRecipient.user_id == user.id))
    assert config is not None
    assert config.weekend_replay_enabled is False
    assert "limit_up_push" in AuthService(db).get_user_permissions(user)

    service.update_recipients(
        LimitUpRecipientUpdateRequest(
            recipients=[LimitUpRecipientUpdateItem(user_id=user.id, enabled=False)]
        ),
        admin,
    )
    db.refresh(user)
    assert "limit_up_push" not in AuthService(db).get_user_permissions(user)


def test_limit_up_report_share_allows_temporary_public_view() -> None:
    """确认已生成报告可以创建临时分享并记录公开访问次数。

    创建日期：2026-05-09
    author: sunshengxian
    """

    db = make_db()
    admin = AppUser(username="admin", password_hash="hash", role="ADMIN", is_active=True)
    analysis = LimitUpAnalysisCache(
        trade_date=date(2026, 5, 8),
        model="deepseek-v4-pro",
        prompt_version="limit-up-v1",
        data_snapshot_hash="hash",
        status="READY",
        title="可分享报告",
        content_html="<h2>报告</h2>",
        generated_at=datetime.now(UTC).replace(tzinfo=None),
    )
    db.add_all([admin, analysis])
    db.commit()
    db.refresh(admin)
    db.refresh(analysis)
    service = LimitUpPushService(
        db,
        settings=Settings(
            llm_api_key="key",
            llm_api_key_file=None,
            tushare_token="token",
            tushare_token_file=None,
        ),
        tushare_client=FakeTushareClient({}),
        notification_service=FakeNotificationService(),
    )

    share = service.create_report_share(analysis.id, 24, admin, "http://localhost:5173")
    public_report = service.get_public_report(share.token)

    stored_share = db.scalar(
        select(LimitUpReportShare).where(LimitUpReportShare.share_token == share.token)
    )
    assert public_report.title == "可分享报告"
    assert public_report.content_html == "<h2>报告</h2>"
    assert share.share_url == f"http://localhost:5173/limit-up-share/{share.token}"
    assert stored_share is not None
    assert stored_share.view_count == 1
    assert stored_share.last_viewed_at is not None


def test_limit_up_report_share_rejects_expired_token() -> None:
    """确认过期分享链接不能继续公开读取报告。

    创建日期：2026-05-09
    author: sunshengxian
    """

    db = make_db()
    analysis = LimitUpAnalysisCache(
        trade_date=date(2026, 5, 8),
        model="deepseek-v4-pro",
        prompt_version="limit-up-v1",
        data_snapshot_hash="hash",
        status="READY",
        title="过期报告",
        content_html="<h2>报告</h2>",
        generated_at=datetime.now(UTC).replace(tzinfo=None),
    )
    db.add(analysis)
    db.flush()
    db.add(
        LimitUpReportShare(
            analysis_id=analysis.id,
            share_token="expired-token",
            expires_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=1),
        )
    )
    db.commit()
    service = LimitUpPushService(
        db,
        settings=Settings(
            llm_api_key="key",
            llm_api_key_file=None,
            tushare_token="token",
            tushare_token_file=None,
        ),
        tushare_client=FakeTushareClient({}),
        notification_service=FakeNotificationService(),
    )

    try:
        service.get_public_report("expired-token")
    except LimitUpPushError as exc:
        assert "无效或已过期" in str(exc)
    else:
        raise AssertionError("过期分享链接不应返回报告")


def test_limit_up_report_share_supports_permanent_link() -> None:
    """确认永久分享链接不依赖过期时间即可公开读取报告。

    创建日期：2026-05-09
    author: sunshengxian
    """

    db = make_db()
    admin = AppUser(username="admin", password_hash="hash", role="ADMIN", is_active=True)
    analysis = LimitUpAnalysisCache(
        trade_date=date(2026, 5, 8),
        model="deepseek-v4-pro",
        prompt_version="limit-up-v1",
        data_snapshot_hash="hash",
        status="READY",
        title="永久报告",
        content_html="<h2>报告</h2>",
        generated_at=datetime.now(UTC).replace(tzinfo=None),
    )
    db.add_all([admin, analysis])
    db.commit()
    db.refresh(admin)
    db.refresh(analysis)
    service = LimitUpPushService(
        db,
        settings=Settings(
            llm_api_key="key",
            llm_api_key_file=None,
            tushare_token="token",
            tushare_token_file=None,
        ),
        tushare_client=FakeTushareClient({}),
        notification_service=FakeNotificationService(),
    )

    share = service.create_report_share(analysis.id, None, admin, "http://localhost:5173")
    public_report = service.get_public_report(share.token)

    assert share.permanent is True
    assert share.expires_at is None
    assert public_report.permanent is True
    assert public_report.expires_at is None
    assert public_report.title == "永久报告"


def test_limit_up_report_share_can_be_listed_and_revoked() -> None:
    """确认管理员可查看已生成分享链接并将其置为失效。

    创建日期：2026-05-09
    author: sunshengxian
    """

    db = make_db()
    admin = AppUser(username="admin", password_hash="hash", role="ADMIN", is_active=True)
    analysis = LimitUpAnalysisCache(
        trade_date=date(2026, 5, 8),
        model="deepseek-v4-pro",
        prompt_version="limit-up-v1",
        data_snapshot_hash="hash",
        status="READY",
        title="可失效报告",
        content_html="<h2>报告</h2>",
        generated_at=datetime.now(UTC).replace(tzinfo=None),
    )
    db.add_all([admin, analysis])
    db.commit()
    db.refresh(admin)
    db.refresh(analysis)
    service = LimitUpPushService(
        db,
        settings=Settings(
            llm_api_key="key",
            llm_api_key_file=None,
            tushare_token="token",
            tushare_token_file=None,
        ),
        tushare_client=FakeTushareClient({}),
        notification_service=FakeNotificationService(),
    )

    share = service.create_report_share(analysis.id, None, admin, "http://localhost:5173")
    shares = service.list_report_shares(analysis.id, "http://localhost:5173")
    revoked = service.revoke_report_share(analysis.id, shares[0].id, "http://localhost:5173")

    assert len(shares) == 1
    assert shares[0].token == share.token
    assert shares[0].status == "ACTIVE"
    assert revoked.status == "REVOKED"
    try:
        service.get_public_report(share.token)
    except LimitUpPushError as exc:
        assert "无效或已过期" in str(exc)
    else:
        raise AssertionError("失效分享链接不应继续公开读取")


def test_latest_analysis_push_is_idempotent_across_polling(monkeypatch) -> None:
    """确认早盘多次轮询同一份报告只推送一次。

    创建日期：2026-05-08
    author: sunshengxian
    """

    db = make_db()
    db.add(ATradeCalendar(exchange="SSE", cal_date=date(2026, 5, 8), is_open=1))
    user = add_user(db)
    fake_notification = FakeNotificationService()
    service = LimitUpPushService(
        db,
        settings=Settings(
            llm_api_key="key",
            llm_api_key_file=None,
            tushare_token="token",
            tushare_token_file=None,
            # 回滚通道回归：REPORT 模式必须与重构前推送行为一致（不触发建议生成）。
            limit_up_push_content_mode="REPORT",
        ),
        tushare_client=FakeTushareClient(
            {
                "kpl_list": [
                    {
                        "ts_code": "000001.SZ",
                        "name": "测试股份",
                        "trade_date": "20260508",
                        "status": "2连板",
                        "theme": "人工智能",
                        "lu_desc": "AI 应用催化",
                    }
                ]
            }
        ),
        notification_service=fake_notification,
    )
    monkeypatch.setattr(service, "_today_local", lambda: date(2026, 5, 9))
    monkeypatch.setattr(service, "_generate_llm_report", lambda context: ("<h2>报告</h2>", "报告"))
    monkeypatch.setattr(service, "_latest_pushplus_log_id", lambda user_id, message_id: None)

    first_analysis, first_pushed = service.ensure_latest_analysis_and_push()
    second_analysis, second_pushed = service.ensure_latest_analysis_and_push()

    assert first_analysis is not None
    assert second_analysis is not None
    assert first_analysis.id == second_analysis.id
    assert first_pushed == 1
    assert second_pushed == 0
    assert fake_notification.sent == [(user.id, "2026-05-08 A股涨停打板复盘", "<h2>报告</h2>")]


def test_limit_up_chain_selection_is_limited_to_twenty() -> None:
    """确认两连三连重点候选最多保留 20 只。

    创建日期：2026-06-05
    author: sunshengxian
    """

    db = make_db()
    service = LimitUpPushService(
        db,
        settings=Settings(
            llm_api_key="key",
            llm_api_key_file=None,
            tushare_token="token",
            tushare_token_file=None,
        ),
        tushare_client=FakeTushareClient({}),
        notification_service=FakeNotificationService(),
    )
    source_rows = [
        {
            "ts_code": f"000{i:03d}.SZ",
            "name": f"测试{i}",
            "status": "2连板",
            "theme": "人工智能",
        }
        for i in range(25)
    ]
    payload = {
        "selected_stocks": [
            {
                "ts_code": row["ts_code"],
                "name": row["name"],
                "selection_reason": "测试入选",
            }
            for row in source_rows
        ]
    }

    selected = service._select_stage_stocks(payload, source_rows, 20)

    assert len(selected) == 20
    assert selected[0]["ts_code"] == "000000.SZ"
    assert selected[-1]["ts_code"] == "000019.SZ"


def test_multi_stage_pipeline_supplements_only_selected_stocks(monkeypatch) -> None:
    """确认多阶段报告只为 LLM 入选股票回调筹码接口。

    创建日期：2026-06-05
    author: sunshengxian
    """

    db = make_db()
    fake_client = FakeTushareClient(
        {
            "cyq_perf": [
                {
                    "ts_code": "000001.SZ",
                    "trade_date": "20260508",
                    "winner_rate": 60,
                    "weight_avg": 10,
                    "cost_50pct": 9.8,
                    "cost_85pct": 10.8,
                    "cost_95pct": 11.2,
                }
            ],
            "cyq_chips": [
                {"ts_code": "000001.SZ", "trade_date": "20260508", "price": 10.5, "percent": 20},
                {"ts_code": "000001.SZ", "trade_date": "20260508", "price": 11.5, "percent": 30},
            ],
        }
    )
    service = LimitUpPushService(
        db,
        settings=Settings(
            llm_api_key="key",
            llm_api_key_file=None,
            tushare_token="token",
            tushare_token_file=None,
        ),
        tushare_client=fake_client,
        notification_service=FakeNotificationService(),
    )
    context = {
        "trade_date": "2026-05-08",
        "data_quality": [],
        "first_board_context": {"stocks": [], "themes": []},
        "chain_board_context": {
            "stocks": [
                {
                    "ts_code": "000001.SZ",
                    "name": "入选二连",
                    "status": "2连板",
                    "theme": "人工智能",
                    "technical": {"close": 10},
                },
                {
                    "ts_code": "000002.SZ",
                    "name": "未入选二连",
                    "status": "2连板",
                    "theme": "机器人",
                    "technical": {"close": 20},
                },
            ]
        },
        "high_board_context": {
            "stocks": [
                {
                    "ts_code": "000003.SZ",
                    "name": "入选高连",
                    "status": "5连板",
                    "theme": "算力",
                    "technical": {"close": 30},
                }
            ]
        },
        "market_context": {"market_emotion": {}, "themes": []},
    }

    def fake_json_stage(
        stage_key: str,
        stage_input: dict[str, object],
        system_prompt: str,
        user_prompt: str,
        fallback_payload: dict[str, object],
        stage_quality: list[dict[str, object]],
    ) -> dict[str, object]:
        stage_quality.append({"stage_key": stage_key, "status": "OK", "message": "测试阶段"})
        if stage_key == "CHAIN_SELECTION":
            return {"selected_stocks": [{"ts_code": "000001.SZ", "selection_reason": "二连前排"}]}
        if stage_key == "HIGH_BOARD_SELECTION":
            return {"selected_stocks": [{"ts_code": "000003.SZ", "selection_reason": "空间板"}]}
        return {"html_fragment": "<h3>首板</h3>", "theme_candidates": []}

    def fake_text_stage(
        stage_key: str,
        stage_input: dict[str, object],
        system_prompt: str,
        user_prompt: str,
        stage_quality: list[dict[str, object]],
    ) -> dict[str, object]:
        stage_quality.append({"stage_key": stage_key, "status": "OK", "message": "测试文本阶段"})
        return {"content": f"<h2>{stage_key}</h2>", "html_fragment": f"<h2>{stage_key}</h2>"}

    monkeypatch.setattr(service, "_run_json_stage", fake_json_stage)
    monkeypatch.setattr(service, "_run_text_stage", fake_text_stage)

    html, raw = service._generate_multi_stage_llm_report(context)

    called_codes = [
        params["ts_code"]
        for api_name, params in fake_client.calls
        if api_name in {"cyq_perf", "cyq_chips"}
    ]
    assert html.startswith("<div")
    assert "FINAL_REPORT" in raw
    assert called_codes == ["000001.SZ", "000001.SZ", "000003.SZ", "000003.SZ"]
    assert [row["ts_code"] for row in context["pipeline"]["selected_chain_stocks"]] == [
        "000001.SZ"
    ]
    assert [row["ts_code"] for row in context["pipeline"]["selected_high_board_stocks"]] == [
        "000003.SZ"
    ]

def test_first_board_selection_supplements_and_pipeline_fields(monkeypatch) -> None:
    """确认首板精选标的进入筹码补数并写回 pipeline 首板字段。

    创建日期：2026-06-12
    author: claude
    """

    db = make_db()
    fake_client = FakeTushareClient({})
    service = LimitUpPushService(
        db,
        settings=Settings(
            llm_api_key="key",
            llm_api_key_file=None,
            tushare_token="token",
            tushare_token_file=None,
        ),
        tushare_client=fake_client,
        notification_service=FakeNotificationService(),
    )
    context = {
        "trade_date": "2026-05-08",
        "data_quality": [],
        "first_board_context": {
            "stocks": [
                {
                    "ts_code": "000010.SZ",
                    "name": "入选首板",
                    "status": "首板",
                    "theme": "人工智能",
                    "technical": {"close": 8},
                },
                {
                    "ts_code": "000011.SZ",
                    "name": "未入选首板",
                    "status": "首板",
                    "theme": "机器人",
                    "technical": {"close": 9},
                },
            ],
            "themes": [],
        },
        "chain_board_context": {"stocks": []},
        "high_board_context": {"stocks": []},
        "market_context": {"market_emotion": {}, "themes": []},
    }

    def fake_json_stage(
        stage_key: str,
        stage_input: dict[str, object],
        system_prompt: str,
        user_prompt: str,
        fallback_payload: dict[str, object],
        stage_quality: list[dict[str, object]],
    ) -> dict[str, object]:
        stage_quality.append({"stage_key": stage_key, "status": "OK", "message": "测试阶段"})
        if stage_key == "FIRST_BOARD_SELECTION":
            return {
                "selected_stocks": [{"ts_code": "000010.SZ", "selection_reason": "强题材首板"}]
            }
        if stage_key in {"CHAIN_SELECTION", "HIGH_BOARD_SELECTION"}:
            return {"selected_stocks": []}
        if stage_key in {"FIRST_BOARD_FOCUS", "CHAIN_FOCUS", "HIGH_BOARD_FOCUS"}:
            # FOCUS 阶段已改 JSON-mode：返回含 html_fragment + 结构化先验的单一对象
            return {"html_fragment": f"<h3>{stage_key}</h3>", "stock_priors": []}
        return {"html_fragment": "<h3>首板</h3>", "theme_candidates": []}

    def fake_text_stage(
        stage_key: str,
        stage_input: dict[str, object],
        system_prompt: str,
        user_prompt: str,
        stage_quality: list[dict[str, object]],
    ) -> dict[str, object]:
        stage_quality.append({"stage_key": stage_key, "status": "OK", "message": "测试文本阶段"})
        return {"content": f"<h2>{stage_key}</h2>", "html_fragment": f"<h2>{stage_key}</h2>"}

    monkeypatch.setattr(service, "_run_json_stage", fake_json_stage)
    monkeypatch.setattr(service, "_run_text_stage", fake_text_stage)

    html, raw = service._generate_multi_stage_llm_report(context)

    # 仅入选的首板股票触发筹码补数，未入选股票不应产生 cyq 调用。
    called_codes = sorted(
        {
            params["ts_code"]
            for api_name, params in fake_client.calls
            if api_name in {"cyq_perf", "cyq_chips"}
        }
    )
    assert called_codes == ["000010.SZ"]
    assert html.startswith("<div")
    pipeline = context["pipeline"]
    assert [row["ts_code"] for row in pipeline["selected_first_board_stocks"]] == ["000010.SZ"]
    assert pipeline["first_board_focus_html"] == "<h3>FIRST_BOARD_FOCUS</h3>"


def test_first_board_selection_is_limited_to_configured_cap(monkeypatch) -> None:
    """确认首板精选数量受配置上限约束（默认 5）。

    创建日期：2026-06-12
    author: claude
    """

    db = make_db()
    service = LimitUpPushService(
        db,
        settings=Settings(
            llm_api_key="key",
            llm_api_key_file=None,
            tushare_token="token",
            tushare_token_file=None,
        ),
        tushare_client=FakeTushareClient({}),
        notification_service=FakeNotificationService(),
    )
    source_rows = [
        {
            "ts_code": f"00010{i}.SZ",
            "name": f"首板{i}",
            "status": "首板",
            "theme": "人工智能",
        }
        for i in range(8)
    ]
    payload = {
        "selected_stocks": [
            {"ts_code": row["ts_code"], "selection_reason": "测试入选"} for row in source_rows
        ]
    }

    selected = service._select_stage_stocks(
        payload,
        source_rows,
        service.settings.limit_up_push_first_board_focus_stock_limit,
    )

    assert len(selected) == 5


def test_first_board_focus_stage_falls_back_on_llm_error(monkeypatch) -> None:
    """确认首板重点分析阶段 LLM 失败时降级为确定性观察表。

    创建日期：2026-06-12
    author: claude
    """

    db = make_db()
    service = LimitUpPushService(
        db,
        settings=Settings(
            llm_api_key="key",
            llm_api_key_file=None,
            tushare_token="token",
            tushare_token_file=None,
        ),
        tushare_client=FakeTushareClient({}),
        notification_service=FakeNotificationService(),
    )

    def boom(prompt: str, system_prompt: str, json_mode: bool = False) -> str:
        raise RuntimeError("llm unavailable")

    monkeypatch.setattr(service, "_chat_completion_with_reasoning", boom)
    stage_quality: list[dict[str, object]] = []

    payload = service._run_text_stage(
        "FIRST_BOARD_FOCUS",
        {
            "trade_date": "2026-05-08",
            "selected_first_board_stocks": [
                {
                    "ts_code": "000010.SZ",
                    "name": "入选首板",
                    "status": "首板",
                    "theme": "人工智能",
                    "selection": {"selection_reason": "强题材首板"},
                }
            ],
            "supplements": {},
            "market_context": {},
        },
        "system",
        "prompt",
        stage_quality,
    )

    assert payload["error_fallback"] is True
    assert "首板重点个股观察" in payload["html_fragment"]
    assert any(item["status"] == "FAILED_FALLBACK" for item in stage_quality)

def _make_advice_service(db) -> LimitUpPushService:
    """构造建议链路测试用服务实例（统一关闭密钥文件读取）。

    创建日期：2026-06-12
    author: claude
    """

    return LimitUpPushService(
        db,
        settings=Settings(
            llm_api_key="key",
            llm_api_key_file=None,
            tushare_token="token",
            tushare_token_file=None,
        ),
        tushare_client=FakeTushareClient({}),
        notification_service=FakeNotificationService(),
    )


def _make_ready_analysis(db, service, with_pipeline: bool = True):
    """构造一份 READY 报告：with_pipeline 控制是否带结构化阶段结果（旧报告兜底场景）。

    创建日期：2026-06-12
    author: claude
    """

    context: dict[str, object] = {"trade_date": "2026-05-08", "market_context": {"themes": []}}
    if with_pipeline:
        context["pipeline"] = {
            "selected_first_board_stocks": [
                {"ts_code": "000010.SZ", "name": "首板股", "status": "首板", "theme": "AI"}
            ],
            "selected_chain_stocks": [
                {"ts_code": "000001.SZ", "name": "二连股", "status": "2连板", "theme": "AI"}
            ],
            "selected_high_board_stocks": [],
            "stock_supplements": {},
            "stage_quality": [],
            "first_board": {"theme_candidates": []},
            "first_board_focus_html": "<h3>首板重点</h3>",
            "chain_focus_html": "<h3>两连三连</h3>",
            "high_board_focus_html": "<h3>高连板</h3>",
        }
    analysis = LimitUpAnalysisCache(
        trade_date=date(2026, 5, 8),
        model=service.settings.limit_up_push_model,
        prompt_version=service.settings.limit_up_push_prompt_version,
        data_snapshot_hash="hash-advice",
        status="READY",
        title="2026-05-08 A股涨停打板复盘",
        content_html="<div><h2>整报</h2></div>",
        content_markdown="```html\n<h2>整报正文</h2>\n```",
        context_json=service._json_dumps(context),
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)
    return analysis


def test_ensure_advice_generates_and_persists(monkeypatch) -> None:
    """确认建议生成成功后五列落库且使用结构化材料与独立 phase。

    创建日期：2026-06-12
    author: claude
    """

    db = make_db()
    service = _make_advice_service(db)
    analysis = _make_ready_analysis(db, service)
    captured: dict[str, object] = {}

    def fake_chat(
        prompt: str, system_prompt: str, json_mode: bool = False, phase: str = "limit_up_analysis"
    ) -> str:
        captured["phase"] = phase
        captured["prompt"] = prompt
        return "<h2>风险提示</h2><p>建议正文</p>"

    monkeypatch.setattr(service, "_chat_completion_with_reasoning", fake_chat)

    result = service.ensure_advice_for_analysis(analysis)

    assert result.advice_status == "READY"
    assert result.advice_html is not None and result.advice_html.startswith("<div")
    assert result.advice_markdown == "<h2>风险提示</h2><p>建议正文</p>"
    assert result.advice_generated_at is not None
    assert result.advice_error is None
    # 报告本体状态不受建议生成影响。
    assert result.status == "READY"
    assert captured["phase"] == "limit_up_advice"
    # 结构化路径的提示词应携带首板入选材料。
    assert "selected_first_board_stocks" in str(captured["prompt"])


def test_ensure_advice_failure_marks_failed_and_lights_fallback_flag(monkeypatch) -> None:
    """确认建议失败置 FAILED、报告保持 READY，且列表降级标识点亮。

    创建日期：2026-06-12
    author: claude
    """

    db = make_db()
    service = _make_advice_service(db)
    analysis = _make_ready_analysis(db, service)

    def boom(
        prompt: str, system_prompt: str, json_mode: bool = False, phase: str = "limit_up_analysis"
    ) -> str:
        raise RuntimeError("advice llm down")

    monkeypatch.setattr(service, "_chat_completion_with_reasoning", boom)

    result = service.ensure_advice_for_analysis(analysis)

    assert result.advice_status == "FAILED"
    assert "advice llm down" in (result.advice_error or "")
    assert result.status == "READY"
    item = service._report_list_item(result)
    assert item.has_stage_fallback is True


def test_ensure_advice_is_idempotent_when_ready(monkeypatch) -> None:
    """确认建议已 READY 时不重调 LLM。

    创建日期：2026-06-12
    author: claude
    """

    db = make_db()
    service = _make_advice_service(db)
    analysis = _make_ready_analysis(db, service)
    analysis.advice_status = "READY"
    analysis.advice_html = "<div>已有建议</div>"
    db.commit()
    calls = {"count": 0}

    def fake_chat(*args: object, **kwargs: object) -> str:
        calls["count"] += 1
        return "<p>x</p>"

    monkeypatch.setattr(service, "_chat_completion_with_reasoning", fake_chat)

    result = service.ensure_advice_for_analysis(analysis)

    assert calls["count"] == 0
    assert result.advice_html == "<div>已有建议</div>"


def test_ensure_advice_respects_generating_lock_and_stale_takeover(monkeypatch) -> None:
    """确认未僵死 GENERATING 直接返回，僵死后允许接管重跑。

    创建日期：2026-06-12
    author: claude
    """

    db = make_db()
    service = _make_advice_service(db)
    analysis = _make_ready_analysis(db, service)
    analysis.advice_status = "GENERATING"
    analysis.updated_at = datetime(2026, 5, 9, 0, 30)
    db.commit()
    calls = {"count": 0}

    def fake_chat(
        prompt: str, system_prompt: str, json_mode: bool = False, phase: str = "limit_up_analysis"
    ) -> str:
        calls["count"] += 1
        return "<p>建议</p>"

    monkeypatch.setattr(service, "_chat_completion_with_reasoning", fake_chat)
    # 未超过 30 分钟阈值：他方持锁，不接管。
    monkeypatch.setattr(service, "_now_naive", lambda: datetime(2026, 5, 9, 0, 40))
    result = service.ensure_advice_for_analysis(analysis)
    assert calls["count"] == 0
    assert result.advice_status == "GENERATING"

    # 超过阈值视为僵死：接管重跑并生成成功。
    monkeypatch.setattr(service, "_now_naive", lambda: datetime(2026, 5, 9, 1, 30))
    result = service.ensure_advice_for_analysis(analysis)
    assert calls["count"] == 1
    assert result.advice_status == "READY"


def test_ensure_advice_failed_cooldown_blocks_auto_retry(monkeypatch) -> None:
    """确认 FAILED 冷却窗口内不自动重试，窗口过后允许重试，force 绕过冷却。

    创建日期：2026-06-12
    author: claude
    """

    db = make_db()
    service = _make_advice_service(db)
    analysis = _make_ready_analysis(db, service)
    analysis.advice_status = "FAILED"
    analysis.advice_error = "first failure"
    analysis.updated_at = datetime(2026, 5, 9, 0, 30)
    db.commit()
    calls = {"count": 0}

    def fake_chat(
        prompt: str, system_prompt: str, json_mode: bool = False, phase: str = "limit_up_analysis"
    ) -> str:
        calls["count"] += 1
        return "<p>建议</p>"

    monkeypatch.setattr(service, "_chat_completion_with_reasoning", fake_chat)
    # 冷却窗口内：不重试。
    monkeypatch.setattr(service, "_now_naive", lambda: datetime(2026, 5, 9, 0, 45))
    result = service.ensure_advice_for_analysis(analysis)
    assert calls["count"] == 0
    assert result.advice_status == "FAILED"

    # force 绕过冷却（管理员重生成端点语义）。
    result = service.ensure_advice_for_analysis(analysis, force=True)
    assert calls["count"] == 1
    assert result.advice_status == "READY"


def test_ensure_advice_old_report_uses_markdown_fallback(monkeypatch) -> None:
    """确认无 pipeline 的旧报告走整报正文兜底材料（剥围栏）。

    创建日期：2026-06-12
    author: claude
    """

    db = make_db()
    service = _make_advice_service(db)
    analysis = _make_ready_analysis(db, service, with_pipeline=False)
    captured: dict[str, object] = {}

    def fake_chat(
        prompt: str, system_prompt: str, json_mode: bool = False, phase: str = "limit_up_analysis"
    ) -> str:
        captured["prompt"] = prompt
        return "<h2>风险提示</h2><p>建议</p>"

    monkeypatch.setattr(service, "_chat_completion_with_reasoning", fake_chat)

    result = service.ensure_advice_for_analysis(analysis)

    assert result.advice_status == "READY"
    prompt_text = str(captured["prompt"])
    # 兜底路径提示词应声明材料为整报原文，并携带剥掉 ``` 围栏后的正文。
    assert "完整打板复盘 HTML 报告原文" in prompt_text
    assert "<h2>整报正文</h2>" in prompt_text
    assert "```" not in prompt_text.split("输入材料：")[1]


def test_stage_prompt_version_mapping_keeps_existing_suffix() -> None:
    """版本映射：未改阶段保持 v3；建议阶段 advice-v1；FOCUS 三阶段 JSON-mode 改造后独立起版
    focus-json-v1（与旧 :v3 HTML 缓存物理隔离）。

    创建日期：2026-06-12
    author: claude
    """

    db = make_db()
    service = _make_advice_service(db)

    # FOCUS 三阶段已改 JSON-mode，后缀独立为 focus-json-v1
    assert service._stage_prompt_version("CHAIN_FOCUS").endswith(":chain_focus:focus-json-v1")
    assert service._stage_prompt_version("FIRST_BOARD_FOCUS").endswith(
        ":first_board_focus:focus-json-v1"
    )
    assert service._stage_prompt_version("HIGH_BOARD_FOCUS").endswith(
        ":high_board_focus:focus-json-v1"
    )
    # 未改阶段仍回退统一后缀 v3；建议阶段独立 advice-v1
    assert service._stage_prompt_version("FINAL_REPORT").endswith(":final_report:v3")
    assert service._stage_prompt_version("INVESTMENT_ADVICE").endswith(
        ":investment_advice:advice-v1"
    )

def _add_push_user(db) -> AppUser:
    """构造可推送接收人（复用既有 add_user 辅助）。

    创建日期：2026-06-12
    author: claude
    """

    return add_user(db)


def test_push_report_advice_mode_pushes_advice_content(monkeypatch) -> None:
    """确认 ADVICE 模式推送正文为建议 HTML、标题为建议口径。

    创建日期：2026-06-12
    author: claude
    """

    db = make_db()
    _add_push_user(db)
    fake_notification = FakeNotificationService()
    service = LimitUpPushService(
        db,
        settings=Settings(
            llm_api_key="key",
            llm_api_key_file=None,
            tushare_token="token",
            tushare_token_file=None,
        ),
        tushare_client=FakeTushareClient({}),
        notification_service=fake_notification,
    )
    analysis = _make_ready_analysis(db, service)
    analysis.advice_status = "READY"
    analysis.advice_html = "<div>建议正文</div>"
    db.commit()
    monkeypatch.setattr(
        service, "_latest_pushplus_log_id", lambda user_id, message_id: None
    )

    pushed = service.push_report(analysis.id, "MANUAL", service._now_naive())

    assert pushed == 1
    _, title, content = fake_notification.sent[0]
    assert title == "2026-05-08 打板投资建议（高风险）"
    assert content == "<div>建议正文</div>"


def test_push_report_advice_pending_backfills_then_pushes(monkeypatch) -> None:
    """确认 PENDING 建议在推送前现场回填（含 MANUAL 与定时入口同路径）。

    创建日期：2026-06-12
    author: claude
    """

    db = make_db()
    _add_push_user(db)
    fake_notification = FakeNotificationService()
    service = LimitUpPushService(
        db,
        settings=Settings(
            llm_api_key="key",
            llm_api_key_file=None,
            tushare_token="token",
            tushare_token_file=None,
        ),
        tushare_client=FakeTushareClient({}),
        notification_service=fake_notification,
    )
    analysis = _make_ready_analysis(db, service)
    calls = {"count": 0}

    def fake_chat(
        prompt: str, system_prompt: str, json_mode: bool = False, phase: str = "limit_up_analysis"
    ) -> str:
        calls["count"] += 1
        return "<h2>风险提示</h2><p>回填建议</p>"

    monkeypatch.setattr(service, "_chat_completion_with_reasoning", fake_chat)
    monkeypatch.setattr(
        service, "_latest_pushplus_log_id", lambda user_id, message_id: None
    )

    scheduled_at = datetime(2026, 5, 9, 0, 30)
    pushed = service.push_report(analysis.id, "DATA_READY", scheduled_at)

    assert pushed == 1
    assert calls["count"] == 1
    assert analysis.advice_status == "READY"
    _, title, content = fake_notification.sent[0]
    assert "打板投资建议" in title
    assert "回填建议" in content
    # 同一业务计划重复轮询不重发（建议已缓存也不再调 LLM）。
    pushed_again = service.push_report(analysis.id, "DATA_READY", scheduled_at)
    assert pushed_again == 0
    assert calls["count"] == 1


def test_push_report_advice_failed_falls_back_to_report(monkeypatch) -> None:
    """确认建议 FAILED 且降级开启时推送整报正文（冷却窗口内不重试）。

    创建日期：2026-06-12
    author: claude
    """

    db = make_db()
    _add_push_user(db)
    fake_notification = FakeNotificationService()
    service = LimitUpPushService(
        db,
        settings=Settings(
            llm_api_key="key",
            llm_api_key_file=None,
            tushare_token="token",
            tushare_token_file=None,
        ),
        tushare_client=FakeTushareClient({}),
        notification_service=fake_notification,
    )
    analysis = _make_ready_analysis(db, service)
    analysis.advice_status = "FAILED"
    analysis.advice_error = "llm down"
    analysis.updated_at = datetime(2026, 5, 9, 0, 30)
    db.commit()
    calls = {"count": 0}

    def fake_chat(*args: object, **kwargs: object) -> str:
        calls["count"] += 1
        return "<p>x</p>"

    monkeypatch.setattr(service, "_chat_completion_with_reasoning", fake_chat)
    monkeypatch.setattr(service, "_now_naive", lambda: datetime(2026, 5, 9, 0, 40))
    monkeypatch.setattr(
        service, "_latest_pushplus_log_id", lambda user_id, message_id: None
    )

    pushed = service.push_report(analysis.id, "MANUAL", datetime(2026, 5, 9, 0, 40))

    assert pushed == 1
    assert calls["count"] == 0
    _, title, content = fake_notification.sent[0]
    assert title == analysis.title
    assert content == analysis.content_html


def test_push_report_advice_failed_without_fallback(monkeypatch) -> None:
    """确认降级关闭时：定时入口跳过不建流水，MANUAL 返回明确错误。

    创建日期：2026-06-12
    author: claude
    """

    db = make_db()
    _add_push_user(db)
    service = LimitUpPushService(
        db,
        settings=Settings(
            llm_api_key="key",
            llm_api_key_file=None,
            tushare_token="token",
            tushare_token_file=None,
            limit_up_push_advice_fallback_to_report=False,
        ),
        tushare_client=FakeTushareClient({}),
        notification_service=FakeNotificationService(),
    )
    analysis = _make_ready_analysis(db, service)
    analysis.advice_status = "FAILED"
    analysis.updated_at = datetime(2026, 5, 9, 0, 30)
    db.commit()
    monkeypatch.setattr(service, "_now_naive", lambda: datetime(2026, 5, 9, 0, 40))

    pushed = service.push_report(analysis.id, "DATA_READY", datetime(2026, 5, 9, 0, 40))
    assert pushed == 0
    deliveries = db.scalars(select(LimitUpPushDelivery)).all()
    assert deliveries == []

    with pytest.raises(LimitUpPushError, match="降级推送已关闭"):
        service.push_report(analysis.id, "MANUAL", datetime(2026, 5, 9, 0, 41))


def test_push_report_advice_generating_skips_scheduled_and_blocks_manual(monkeypatch) -> None:
    """确认未僵死 GENERATING：定时跳过，MANUAL 提示稍后重试。

    创建日期：2026-06-12
    author: claude
    """

    db = make_db()
    _add_push_user(db)
    service = LimitUpPushService(
        db,
        settings=Settings(
            llm_api_key="key",
            llm_api_key_file=None,
            tushare_token="token",
            tushare_token_file=None,
        ),
        tushare_client=FakeTushareClient({}),
        notification_service=FakeNotificationService(),
    )
    analysis = _make_ready_analysis(db, service)
    analysis.advice_status = "GENERATING"
    analysis.updated_at = datetime(2026, 5, 9, 0, 30)
    db.commit()
    monkeypatch.setattr(service, "_now_naive", lambda: datetime(2026, 5, 9, 0, 35))

    pushed = service.push_report(analysis.id, "DATA_READY", datetime(2026, 5, 9, 0, 35))
    assert pushed == 0

    with pytest.raises(LimitUpPushError, match="正在生成中"):
        service.push_report(analysis.id, "MANUAL", datetime(2026, 5, 9, 0, 36))


def test_weekend_replay_uses_cached_advice_without_llm(monkeypatch) -> None:
    """确认周末复推命中已缓存建议时零新增 LLM 调用。

    创建日期：2026-06-12
    author: claude
    """

    db = make_db()
    _add_push_user(db)
    fake_notification = FakeNotificationService()
    service = LimitUpPushService(
        db,
        settings=Settings(
            llm_api_key="key",
            llm_api_key_file=None,
            tushare_token="token",
            tushare_token_file=None,
        ),
        tushare_client=FakeTushareClient({}),
        notification_service=fake_notification,
    )
    analysis = _make_ready_analysis(db, service)
    analysis.advice_status = "READY"
    analysis.advice_html = "<div>周五建议</div>"
    db.commit()
    calls = {"count": 0}

    def fake_chat(*args: object, **kwargs: object) -> str:
        calls["count"] += 1
        return "<p>x</p>"

    monkeypatch.setattr(service, "_chat_completion_with_reasoning", fake_chat)
    monkeypatch.setattr(
        service, "_latest_pushplus_log_id", lambda user_id, message_id: None
    )
    # 2026-05-09 是周六，最近周五为 2026-05-08（已 READY 且带建议）。
    monkeypatch.setattr(service, "_today_local", lambda: date(2026, 5, 9))

    replay_analysis, pushed = service.push_weekend_replay()

    assert replay_analysis is not None and replay_analysis.id == analysis.id
    assert pushed == 1
    assert calls["count"] == 0
    _, title, content = fake_notification.sent[0]
    assert "打板投资建议" in title
    assert content == "<div>周五建议</div>"

def test_select_stage_stocks_respects_legal_empty_selection() -> None:
    """确认 LLM 合法空选不被强制兜底，仅失败 payload 或幻觉代码才兜底排序。

    创建日期：2026-06-12
    author: claude
    """

    db = make_db()
    service = _make_advice_service(db)
    source_rows = [
        {"ts_code": "000010.SZ", "name": "首板A", "status": "首板", "theme": "AI"},
        {"ts_code": "000011.SZ", "name": "首板B", "status": "首板", "theme": "机器人"},
    ]

    # 合法空选（键存在且为空列表）：尊重"宁缺毋滥"，返回空名单。
    assert service._select_stage_stocks({"selected_stocks": []}, source_rows, 5) == []
    # 解析失败兜底 payload：仍走确定性排序兜底。
    fallback = service._select_stage_stocks(
        {"selected_stocks": [], "parse_fallback": True}, source_rows, 5
    )
    assert len(fallback) == 2
    # 全部为无法映射的幻觉代码：视为异常输出，走确定性兜底。
    hallucinated = service._select_stage_stocks(
        {"selected_stocks": [{"ts_code": "999999.SZ"}]}, source_rows, 5
    )
    assert len(hallucinated) == 2


def test_force_regenerate_bypasses_stage_cache(monkeypatch) -> None:
    """确认 force 重生成跳过阶段缓存真正重调 LLM 并覆盖建议内容。

    创建日期：2026-06-12
    author: claude
    """

    db = make_db()
    service = _make_advice_service(db)
    analysis = _make_ready_analysis(db, service)
    calls = {"count": 0}

    def fake_chat(
        prompt: str, system_prompt: str, json_mode: bool = False, phase: str = "limit_up_analysis"
    ) -> str:
        calls["count"] += 1
        return f"<h2>风险提示</h2><p>第{calls['count']}版建议</p>"

    monkeypatch.setattr(service, "_chat_completion_with_reasoning", fake_chat)

    first = service.ensure_advice_for_analysis(analysis)
    assert calls["count"] == 1
    assert "第1版建议" in (first.advice_markdown or "")

    # 同输入哈希已有 READY 阶段缓存：force 必须绕过缓存重调 LLM 并覆盖旧内容。
    regenerated = service.ensure_advice_for_analysis(analysis, force=True)
    assert calls["count"] == 2
    assert "第2版建议" in (regenerated.advice_markdown or "")

def test_ensure_advice_empty_llm_output_marks_failed(monkeypatch) -> None:
    """确认 LLM 返回空内容时建议置 FAILED（守卫不被 html_fragment 包装绕过）。

    创建日期：2026-06-12
    author: claude
    """

    db = make_db()
    service = _make_advice_service(db)
    analysis = _make_ready_analysis(db, service)

    def empty_chat(
        prompt: str, system_prompt: str, json_mode: bool = False, phase: str = "limit_up_analysis"
    ) -> str:
        return "   "

    monkeypatch.setattr(service, "_chat_completion_with_reasoning", empty_chat)

    result = service.ensure_advice_for_analysis(analysis)

    assert result.advice_status == "FAILED"
    assert "输出为空" in (result.advice_error or "")
    # 报告本体不受影响，推送层据 FAILED 走降级整报路径。
    assert result.status == "READY"


def test_manual_push_recovers_from_stale_generating_advice(monkeypatch) -> None:
    """确认 MANUAL 推送可接管僵死 GENERATING 建议（进程崩溃后的恢复通道）。

    创建日期：2026-06-12
    author: claude
    """

    db = make_db()
    _add_push_user(db)
    fake_notification = FakeNotificationService()
    service = LimitUpPushService(
        db,
        settings=Settings(
            llm_api_key="key",
            llm_api_key_file=None,
            tushare_token="token",
            tushare_token_file=None,
        ),
        tushare_client=FakeTushareClient({}),
        notification_service=fake_notification,
    )
    analysis = _make_ready_analysis(db, service)
    analysis.advice_status = "GENERATING"
    analysis.updated_at = datetime(2026, 5, 9, 0, 0)
    db.commit()
    calls = {"count": 0}

    def fake_chat(
        prompt: str, system_prompt: str, json_mode: bool = False, phase: str = "limit_up_analysis"
    ) -> str:
        calls["count"] += 1
        return "<h2>风险提示</h2><p>接管后建议</p>"

    monkeypatch.setattr(service, "_chat_completion_with_reasoning", fake_chat)
    monkeypatch.setattr(
        service, "_latest_pushplus_log_id", lambda user_id, message_id: None
    )
    # 超过 30 分钟僵死阈值：MANUAL 推送应接管重生成后推送建议，而非永久报"生成中"。
    monkeypatch.setattr(service, "_now_naive", lambda: datetime(2026, 5, 9, 1, 0))

    pushed = service.push_report(analysis.id, "MANUAL", datetime(2026, 5, 9, 1, 0))

    assert pushed == 1
    assert calls["count"] == 1
    _, title, content = fake_notification.sent[0]
    assert "打板投资建议" in title
    assert "接管后建议" in content
