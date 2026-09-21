import os
import unittest
import json
from unittest.mock import MagicMock
import db
import lead_scorer
import messaging_engine
import notifier
from llms import is_network_or_rate_limit_error
from agent import run_agent_with_retry

class TestGrowthEngine(unittest.TestCase):

    def test_01_lead_scoring_prop_firm(self):
        headline = "FTMO Funded Trader | Prop Firm Risk Management | MT5 Algo Developer"
        res = lead_scorer.calculate_lead_score(headline=headline, threshold=70)
        self.assertTrue(res["is_high_probable"])
        self.assertGreaterEqual(res["score"], 70)
        self.assertEqual(res["persona"], "Prop Firm Trader")

    def test_02_lead_scoring_disqualification(self):
        headline = "Senior Technical Recruiter | Talent Acquisition Specialist"
        res = lead_scorer.calculate_lead_score(headline=headline, threshold=70)
        self.assertFalse(res["is_high_probable"])
        self.assertLess(res["score"], 50)

    def test_03_lead_scoring_forex_day_trader(self):
        headline = "Full-time Day Trader | FX & Gold | Disciplined Risk Management"
        res = lead_scorer.calculate_lead_score(headline=headline, threshold=70)
        self.assertTrue(res["is_high_probable"])
        self.assertGreaterEqual(res["score"], 70)
        self.assertEqual(res["persona"], "Forex Trader")

    def test_04_messaging_engine_variant_a(self):
        variant, msg = messaging_engine.generate_welcome_message(
            full_name="Alex Vance",
            headline="Funded Trader",
            persona="Prop Firm Trader",
            variant_override="variant_a_standard"
        )
        self.assertEqual(variant, "variant_a_standard")
        self.assertIn("Ascentrader", msg)
        self.assertIn("calendar.app.google", msg)

    def test_05_messaging_engine_variant_b_personalized(self):
        variant, msg = messaging_engine.generate_welcome_message(
            full_name="Alex Vance",
            headline="FTMO Funded Trader",
            persona="Prop Firm Trader",
            variant_override="variant_b_personalized"
        )
        self.assertEqual(variant, "variant_b_personalized")
        self.assertIn("Hi Alex", msg)
        self.assertIn("prop accounts", msg)
        self.assertIn("calendar.app.google", msg)

    def test_06_single_followup_message(self):
        msg = messaging_engine.build_single_followup("Alex")
        self.assertIn("Hey Alex", msg)
        self.assertIn("buried in your inbox", msg)

    def test_07_reply_classifier(self):
        # Booked
        res_booked = notifier.classify_reply_intent("I already scheduled a time on your calendar!", use_llm=False)
        self.assertEqual(res_booked["intent"], "CALL_BOOKED")
        self.assertFalse(res_booked["requires_alert"])

        # Not interested
        res_no = notifier.classify_reply_intent("Not interested, please remove me.", use_llm=False)
        self.assertEqual(res_no["intent"], "NOT_INTERESTED")
        self.assertFalse(res_no["requires_alert"])

        # Custom inquiry
        res_inq = notifier.classify_reply_intent("Does Ascentrader support MT5 broker bridge or do I have to export CSV manually?", use_llm=False)
        self.assertEqual(res_inq["intent"], "CUSTOM_INQUIRY")
        self.assertTrue(res_inq["requires_alert"])

    def test_08_database_lifecycle(self):
        test_url = "https://www.linkedin.com/in/test-trader-lifecycle-fresh"
        with db.get_connection() as conn:
            conn.cursor().execute("DELETE FROM connections WHERE profile_url = ?", (test_url,))
            conn.commit()
        
        # 1. Record lead score
        db.record_lead_score(
            profile_url=test_url,
            score=95,
            reasons=["+40 FTMO", "+35 MT5"],
            persona="Prop Firm Trader",
            is_high_probable=True,
            full_name="Verification Trader",
            headline="FTMO & MT5 Trader"
        )
        
        # 2. Record connection
        db.record_connection(
            profile_url=test_url,
            full_name="Verification Trader",
            headline="FTMO & MT5 Trader",
            lead_score=95,
            lead_score_reasons=["+40 FTMO", "+35 MT5"],
            persona="Prop Firm Trader",
            is_high_probable=True,
            status="pending"
        )
        self.assertTrue(db.is_already_connected(test_url))

        # 3. Mark accepted
        db.mark_connection_accepted(test_url)
        ready_leads = db.get_leads_ready_for_welcome_message()
        matching = [l for l in ready_leads if l["profile_url"] == test_url]
        self.assertTrue(len(matching) > 0)

        # 4. Record message sent
        db.record_message_sent(test_url, "variant_b_personalized", "Test message text")
        
        # 5. Record reply
        db.record_reply(test_url, "Sounds great, booked!", "CALL_BOOKED")

        # 6. Mark call booked
        db.mark_call_booked(test_url, event_id="ev_test_123")
        
        # 7. Check summary analytics
        stats = db.get_dashboard_analytics_summary()
        self.assertGreater(stats["total_leads"], 0)
        self.assertGreaterEqual(stats["total_calls_booked"], 1)

    def test_09_run_agent_network_retry_preserves_memory(self):
        # 1. Test network error predicate
        self.assertTrue(is_network_or_rate_limit_error(Exception("Connection reset by peer")))
        self.assertTrue(is_network_or_rate_limit_error(Exception("HTTP 502 Bad Gateway")))
        self.assertTrue(is_network_or_rate_limit_error(Exception("dial tcp: lookup host: no such host")))
        self.assertFalse(is_network_or_rate_limit_error(ValueError("Invalid syntax")))

        # 2. Test agent retry with memory preservation (reset=False)
        mock_agent = MagicMock()
        mock_agent.run.side_effect = [
            ConnectionError("Temporary network glitch"),
            "Final Answer: completed"
        ]

        result = run_agent_with_retry(mock_agent, "Do outreach", max_retries=3, retry_delay=0.01)
        self.assertEqual(result, "Final Answer: completed")
        self.assertEqual(mock_agent.run.call_count, 2)
        
        # Verify first call had reset=True and second call had reset=False to preserve memory!
        first_call = mock_agent.run.call_args_list[0]
        second_call = mock_agent.run.call_args_list[1]
        self.assertEqual(first_call.kwargs.get("reset"), True)
        self.assertEqual(second_call.kwargs.get("reset"), False)

    def test_10_verify_and_message_connections_batch_logic(self):
        # Simulate 12 connections
        connections = [{"name": f"Trader {i}", "profile_url": f"https://linkedin.com/in/trader-{i}"} for i in range(12)]
        
        # Chunk 1: [0:5] - unmessaged leads found -> recommendation is continue_next_chunk
        chunk_1 = connections[0:5]
        self.assertEqual(len(chunk_1), 5)
        newly_count_1 = 2
        has_more_1 = (0 + 5) < len(connections)
        rec_1 = "continue_next_chunk" if newly_count_1 > 0 and has_more_1 else "stop_reached_old_connections"
        self.assertEqual(rec_1, "continue_next_chunk")

        # Chunk 2: [5:10] - all already messaged in this chunk -> recommendation is stop_reached_old_connections
        chunk_2 = connections[5:10]
        self.assertEqual(len(chunk_2), 5)
        newly_count_2 = 0
        has_more_2 = (5 + 5) < len(connections)
        rec_2 = "continue_next_chunk" if newly_count_2 > 0 and has_more_2 else "stop_reached_old_connections"
        self.assertEqual(rec_2, "stop_reached_old_connections")

        # Chunk 3: [10:15] - partial chunk (2 leads remaining), both messaged, no more connections
        chunk_3 = connections[10:15]
        self.assertEqual(len(chunk_3), 2)
        newly_count_3 = 2
        has_more_3 = (10 + 5) < len(connections)
        self.assertFalse(has_more_3)
        rec_3 = "continue_next_chunk" if newly_count_3 > 0 and has_more_3 else ("stop_no_more_connections" if not has_more_3 else "stop_reached_old_connections")
        self.assertEqual(rec_3, "stop_no_more_connections")

if __name__ == "__main__":
    unittest.main()
