import unittest
from unittest.mock import MagicMock, patch
import sys
import os


sys.path.append(os.path.join(os.getcwd()))

from utils import generate_security_insights

class TestSecurityInsights(unittest.TestCase):
    def test_high_churn_insight(self):
        metrics = {
            'mod_ratio': 80,
            'verification_level': 2,
            'mfa_level': 1,
            'explicit_filter': 2,
            'churn_rate': 20.0,  
            'participation_rate': 15,
            'reply_ratio': 60,
            'voice_hours_per_dau': 0.5
        }
        insights = generate_security_insights(metrics)
        self.assertTrue(any("vysoký odliv" in i.lower() for i in insights))
        print("✅ High churn insight verified")

    def test_exodus_insight(self):
        metrics = {
            'mod_ratio': 80,
            'verification_level': 2,
            'mfa_level': 1,
            'explicit_filter': 2,
            'churn_rate': 35.0,  
            'participation_rate': 15,
            'reply_ratio': 60,
            'voice_hours_per_dau': 0.5
        }
        insights = generate_security_insights(metrics)
        self.assertTrue(any("exodus" in i.lower() for i in insights))
        print("✅ Exodus insight verified")

    def test_low_mod_score_insight(self):
        metrics = {
            'mod_ratio': 50,  
            'users_per_mod': 150,
            'verification_level': 2,
            'mfa_level': 1,
            'explicit_filter': 2,
            'churn_rate': 2.0,
            'participation_rate': 15,
            'reply_ratio': 60,
            'voice_hours_per_dau': 0.5
        }
        insights = generate_security_insights(metrics)
        self.assertTrue(any("nedostatek moderátorů" in i.lower() for i in insights))
        print("✅ Low mod score insight verified")

    def test_low_participation_insight(self):
        metrics = {
            'mod_ratio': 80,
            'verification_level': 2,
            'mfa_level': 1,
            'explicit_filter': 2,
            'churn_rate': 2.0,
            'participation_rate': 5,  
            'reply_ratio': 60,
            'voice_hours_per_dau': 0.5
        }
        insights = generate_security_insights(metrics)
        self.assertTrue(any("nízké zapojení" in i.lower() for i in insights))
        print("✅ Low participation insight verified")

    def test_low_reply_ratio_insight(self):
        metrics = {
            'mod_ratio': 80,
            'verification_level': 2,
            'mfa_level': 1,
            'explicit_filter': 2,
            'churn_rate': 2.0,
            'participation_rate': 15,
            'reply_ratio': 10,  
            'voice_hours_per_dau': 0.5
        }
        insights = generate_security_insights(metrics)
        self.assertTrue(any("monology" in i.lower() for i in insights))
        print("✅ Low reply ratio insight verified")

if __name__ == '__main__':
    unittest.main()
