-- 替换 <readonly_user> 和 <readonly_password> 后手工执行。
CREATE USER IF NOT EXISTS '<readonly_user>'@'localhost' IDENTIFIED BY '<readonly_password>';
GRANT SELECT ON stock_ah_ai.v_latest_ah_premium TO '<readonly_user>'@'localhost';
GRANT SELECT ON stock_ah_ai.v_ah_premium_trend TO '<readonly_user>'@'localhost';
GRANT SELECT ON stock_ah_ai.v_latest_official_ah_premium TO '<readonly_user>'@'localhost';
GRANT SELECT ON stock_ah_ai.v_official_ah_premium_trend TO '<readonly_user>'@'localhost';
GRANT SELECT ON stock_ah_ai.v_latest_hk_connect_official_ah_premium TO '<readonly_user>'@'localhost';
GRANT SELECT ON stock_ah_ai.v_watchlist_opportunity TO '<readonly_user>'@'localhost';
GRANT SELECT ON stock_ah_ai.v_stock_selection_latest TO '<readonly_user>'@'localhost';
GRANT SELECT ON stock_ah_ai.v_stock_selection_history TO '<readonly_user>'@'localhost';
GRANT SELECT ON stock_ah_ai.v_stock_factor_dictionary TO '<readonly_user>'@'localhost';
GRANT SELECT ON stock_ah_ai.v_stock_quote_valuation_trend TO '<readonly_user>'@'localhost';
GRANT SELECT ON stock_ah_ai.v_stock_financial_period_summary TO '<readonly_user>'@'localhost';
GRANT SELECT ON stock_ah_ai.v_stock_research_context_latest TO '<readonly_user>'@'localhost';
GRANT SELECT ON stock_ah_ai.v_market_data_fetch_health TO '<readonly_user>'@'localhost';
GRANT SELECT ON stock_ah_ai.v_sync_health TO '<readonly_user>'@'localhost';
GRANT SELECT ON stock_ah_ai.v_data_quality_issues TO '<readonly_user>'@'localhost';
FLUSH PRIVILEGES;
